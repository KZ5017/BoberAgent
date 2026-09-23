"""Core application boundary for Credential metadata and deliberate Secret reveal."""

from __future__ import annotations

from boberagent_contracts import CredentialRef, Event, MissionRef

from boberagent_core.models import Credential
from boberagent_core.persistence import CoreDatabase
from boberagent_core.secrets import CoreSecretService, RevealedSecret


class CoreCredentialService:
    def __init__(self, database: CoreDatabase) -> None:
        self._database = database
        self._secrets = CoreSecretService(database)

    def get(self, credential_ref: CredentialRef) -> Credential | None:
        with self._database.unit_of_work() as work:
            return work.credentials.get(credential_ref)

    def list_for_mission(self, mission_ref: MissionRef) -> tuple[Credential, ...]:
        with self._database.unit_of_work() as work:
            if work.missions.get(mission_ref) is None:
                raise KeyError(f"unknown Mission: {mission_ref}")
            return work.credentials.list_for_mission(mission_ref)

    def reveal(
        self,
        credential_ref: CredentialRef,
        *,
        role: str,
        mission_ref: MissionRef,
    ) -> RevealedSecret:
        credential = self.get(credential_ref)
        if credential is None or credential.mission_ref != mission_ref:
            raise KeyError(f"unknown Credential for Mission: {credential_ref}")
        matching = tuple(binding for binding in credential.secrets if binding.role == role)
        if len(matching) != 1:
            raise KeyError(f"Credential has no Secret role {role!r}: {credential_ref}")
        return self._secrets.reveal_for_operator(
            matching[0].secret_ref,
            mission_ref=mission_ref,
            purpose=f"operator.credential.reveal:{role}",
        )

    def available_events(self, mission_ref: MissionRef) -> tuple[Event, ...]:
        with self._database.unit_of_work() as work:
            return work.core_events.list_for_mission(mission_ref, event_type="credential.available")
