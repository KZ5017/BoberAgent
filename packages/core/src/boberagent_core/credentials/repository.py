"""Explicit Credential and Core-owned domain Event repositories."""

from __future__ import annotations

from copy import deepcopy

from boberagent_contracts import (
    ArtifactRef,
    CredentialRef,
    DomainRef,
    Event,
    EventRef,
    IdentityRef,
    MissionRef,
    ObservationRef,
    SecretRef,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from boberagent_core.models import Credential, CredentialSecretBinding, CredentialStatus
from boberagent_core.persistence.orm import CoreEventRow, CredentialRow
from boberagent_core.persistence.repositories import _flush_identity


class CredentialRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, credential_ref: CredentialRef) -> Credential | None:
        row = self._session.get(CredentialRow, str(credential_ref))
        return None if row is None else _credential_from_row(row)

    def list_for_mission(self, mission_ref: MissionRef) -> tuple[Credential, ...]:
        rows = self._session.scalars(
            select(CredentialRow)
            .where(CredentialRow.mission_id == str(mission_ref))
            .order_by(CredentialRow.credential_id)
        )
        return tuple(_credential_from_row(row) for row in rows)

    def upsert_candidate(self, credential: Credential) -> Credential:
        row = self._session.get(CredentialRow, str(credential.credential_ref))
        if row is None:
            self._session.add(
                CredentialRow(
                    credential_id=str(credential.credential_ref),
                    mission_id=str(credential.mission_ref),
                    credential_type=credential.credential_type,
                    username=credential.username,
                    identity_ref=(
                        None if credential.identity_ref is None else str(credential.identity_ref)
                    ),
                    secret_bindings_json=[
                        {"role": binding.role, "secret_ref": str(binding.secret_ref)}
                        for binding in credential.secrets
                    ],
                    scope_refs_json=[str(ref) for ref in credential.scope_refs],
                    status=credential.status.value,
                    source_observation_refs_json=[
                        str(ref) for ref in credential.source_observation_refs
                    ],
                    source_artifact_refs_json=[str(ref) for ref in credential.source_artifact_refs],
                    created_at=credential.created_at,
                    updated_at=credential.updated_at,
                    metadata_json=deepcopy(credential.metadata),
                )
            )
            _flush_identity(self._session, credential.credential_ref)
            created = self.get(credential.credential_ref)
            assert created is not None
            return created

        existing = _credential_from_row(row)
        if (
            existing.mission_ref != credential.mission_ref
            or existing.credential_type != credential.credential_type
            or existing.username != credential.username
            or existing.identity_ref != credential.identity_ref
            or existing.secrets != credential.secrets
        ):
            raise ValueError(
                f"CredentialRef has conflicting authentication identity: "
                f"{credential.credential_ref}"
            )
        merged = deepcopy(row.metadata_json)
        for key, value in credential.metadata.items():
            if key in merged and merged[key] != value:
                raise ValueError(f"Credential metadata conflict for field {key!r}")
            merged[key] = deepcopy(value)
        row.source_observation_refs_json = sorted(
            {
                *row.source_observation_refs_json,
                *(str(ref) for ref in credential.source_observation_refs),
            }
        )
        row.source_artifact_refs_json = sorted(
            {
                *row.source_artifact_refs_json,
                *(str(ref) for ref in credential.source_artifact_refs),
            }
        )
        row.scope_refs_json = sorted(
            {*row.scope_refs_json, *(str(ref) for ref in credential.scope_refs)}
        )
        row.metadata_json = merged
        row.created_at = min(row.created_at, credential.created_at)
        row.updated_at = max(row.updated_at, credential.updated_at)
        self._session.flush()
        return _credential_from_row(row)

    def set_status(self, credential_ref: CredentialRef, status: CredentialStatus) -> Credential:
        row = self._session.get(CredentialRow, str(credential_ref))
        if row is None:
            raise KeyError(f"unknown Credential: {credential_ref}")
        row.status = status.value
        self._session.flush()
        return _credential_from_row(row)


class CoreEventRepository:
    """Tiny durable Core Event journal; not an Event Bus or workflow dispatcher."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: Event) -> Event:
        row = self._session.get(CoreEventRow, str(event.event_id))
        if row is None:
            self._session.add(
                CoreEventRow(
                    event_id=str(event.event_id),
                    event_type=event.type,
                    timestamp=event.timestamp,
                    mission_id=str(event.mission_ref),
                    source_ref=str(event.source_ref),
                    payload_json=deepcopy(event.payload),
                )
            )
            _flush_identity(self._session, event.event_id)
            return event
        existing = _event_from_row(row)
        if existing != event:
            raise ValueError(f"EventRef has conflicting immutable content: {event.event_id}")
        return existing

    def get(self, event_ref: EventRef) -> Event | None:
        row = self._session.get(CoreEventRow, str(event_ref))
        return None if row is None else _event_from_row(row)

    def list_for_mission(
        self, mission_ref: MissionRef, *, event_type: str | None = None
    ) -> tuple[Event, ...]:
        statement = select(CoreEventRow).where(CoreEventRow.mission_id == str(mission_ref))
        if event_type is not None:
            statement = statement.where(CoreEventRow.event_type == event_type)
        rows = self._session.scalars(
            statement.order_by(CoreEventRow.timestamp, CoreEventRow.event_id)
        )
        return tuple(_event_from_row(row) for row in rows)


def _credential_from_row(row: CredentialRow) -> Credential:
    return Credential(
        credential_ref=CredentialRef(row.credential_id),
        mission_ref=MissionRef(row.mission_id),
        credential_type=row.credential_type,
        username=row.username,
        identity_ref=None if row.identity_ref is None else IdentityRef(row.identity_ref),
        secrets=tuple(
            CredentialSecretBinding(
                role=str(binding["role"]),
                secret_ref=SecretRef(str(binding["secret_ref"])),
            )
            for binding in row.secret_bindings_json
        ),
        scope_refs=tuple(DomainRef(ref) for ref in row.scope_refs_json),
        status=CredentialStatus(row.status),
        source_observation_refs=tuple(
            ObservationRef(ref) for ref in row.source_observation_refs_json
        ),
        source_artifact_refs=tuple(ArtifactRef(ref) for ref in row.source_artifact_refs_json),
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=deepcopy(row.metadata_json),
    )


def _event_from_row(row: CoreEventRow) -> Event:
    return Event(
        event_id=EventRef(row.event_id),
        type=row.event_type,
        timestamp=row.timestamp,
        mission_ref=MissionRef(row.mission_id),
        source_ref=DomainRef(row.source_ref),
        payload=deepcopy(row.payload_json),
    )
