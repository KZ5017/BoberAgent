"""Deterministic ``credential.candidate`` World State materializer."""

from __future__ import annotations

import json
from uuid import UUID, uuid5

from boberagent_contracts import CredentialRef, Event, EventRef, Observation

from boberagent_core.models import (
    Credential,
    CredentialSecretBinding,
    CredentialStatus,
    SecretStatus,
)
from boberagent_core.persistence.repositories import CoreUnitOfWork

from .models import CredentialCandidateValue

_CREDENTIAL_NAMESPACE = UUID("59219d68-13dc-5baf-9199-6b8d16d709d5")
_EVENT_NAMESPACE = UUID("44786edc-bc60-59c0-aa06-74dbc7bc707d")


def credential_ref_for_candidate(
    mission_ref: str, value: CredentialCandidateValue
) -> CredentialRef:
    identity = json.dumps(
        {
            "mission_ref": mission_ref,
            "credential_type": value.credential_type,
            "username": value.username,
            "identity_ref": None if value.identity_ref is None else str(value.identity_ref),
            "secrets": sorted((binding.role, str(binding.secret_ref)) for binding in value.secrets),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return CredentialRef(f"credential:{uuid5(_CREDENTIAL_NAMESPACE, identity)}")


class CredentialCandidateReducer:
    observation_type = "credential.candidate"

    def reduce(self, observation: Observation, unit_of_work: CoreUnitOfWork) -> Credential:
        run = unit_of_work.runs.get(observation.run_ref)
        if run is None:
            raise ValueError("credential.candidate references an unknown CapabilityRun")
        value = CredentialCandidateValue.model_validate(observation.value)
        for binding in value.secrets:
            secret = unit_of_work.secrets.get(binding.secret_ref)
            if (
                secret is None
                or secret.mission_ref != run.mission_ref
                or secret.status is not SecretStatus.AVAILABLE
            ):
                raise ValueError("credential.candidate references a Secret outside its Mission")

        credential_ref = credential_ref_for_candidate(str(run.mission_ref), value)
        credential = unit_of_work.credentials.upsert_candidate(
            Credential(
                credential_ref=credential_ref,
                mission_ref=run.mission_ref,
                credential_type=value.credential_type,
                username=value.username,
                identity_ref=value.identity_ref,
                secrets=tuple(
                    CredentialSecretBinding(
                        role=binding.role,
                        secret_ref=binding.secret_ref,
                    )
                    for binding in value.secrets
                ),
                scope_refs=value.scope_refs,
                status=CredentialStatus.CANDIDATE,
                source_observation_refs=(observation.observation_id,),
                source_artifact_refs=observation.evidence_refs,
                created_at=observation.observed_at,
                updated_at=observation.observed_at,
                metadata=value.metadata,
            )
        )
        event_ref = EventRef(f"event:{uuid5(_EVENT_NAMESPACE, str(observation.observation_id))}")
        unit_of_work.core_events.append(
            Event(
                event_id=event_ref,
                type="credential.available",
                timestamp=observation.observed_at,
                mission_ref=run.mission_ref,
                source_ref=observation.observation_id,
                payload={
                    "credential_ref": str(credential.credential_ref),
                    "credential_type": credential.credential_type,
                    "username": credential.username,
                    "status": credential.status.value,
                    "secret_refs": [str(binding.secret_ref) for binding in credential.secrets],
                    "scope_refs": [str(ref) for ref in credential.scope_refs],
                },
            )
        )
        return credential
