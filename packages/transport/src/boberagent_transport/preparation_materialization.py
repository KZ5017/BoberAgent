"""Transport-neutral request and evidence for one authorized E4 source materialization."""

from __future__ import annotations

import hashlib
from typing import Literal

from boberagent_contracts import (
    ArtifactRef,
    CapabilityRunRef,
    DomainRef,
    ExecutionPlanRef,
    MissionRef,
    PreparationBudgets,
    PreparationPermitRef,
    RuntimePreparationRef,
    Sha256Digest,
)
from boberagent_contracts.runtime_preparation import ConfinementFeature
from pydantic import AwareDatetime, Field, ValidationError

from .errors import MalformedMessage
from .models import NodeIdentifier, TransportMessageId, TransportModel

MATERIALIZATION_PROTOCOL_VERSION: Literal["preparation-materialization-v1"] = (
    "preparation-materialization-v1"
)


def materialization_message_id(
    permit_ref: PreparationPermitRef, action: Literal["CHECK", "MATERIALIZE"] = "MATERIALIZE"
) -> TransportMessageId:
    digest = hashlib.sha256(f"materialize\0{permit_ref}\0{action}".encode()).hexdigest()
    return TransportMessageId(f"preparation-materialization:{digest}")


class MaterializeSourceRequest(TransportModel):
    protocol_version: Literal["preparation-materialization-v1"] = MATERIALIZATION_PROTOCOL_VERSION
    message_type: Literal["preparation.materialize.source"] = "preparation.materialize.source"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    permit_sha256: Sha256Digest
    run_ref: CapabilityRunRef
    action: Literal["CHECK", "MATERIALIZE"] = "MATERIALIZE"
    timestamp: AwareDatetime


class MaterializationPreflight(TransportModel):
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    run_ref: CapabilityRunRef
    raw_artifact_ref: ArtifactRef
    raw_sha256: Sha256Digest
    manifest_artifact_ref: ArtifactRef
    manifest_sha256: Sha256Digest
    confinement_backend: str
    confinement_version: str
    proven_features: tuple[ConfinementFeature, ...]


class MaterializationEvidence(TransportModel):
    """Observed E4 source evidence; not E5 readiness or execution authorization."""

    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    permit_sha256: Sha256Digest
    run_ref: CapabilityRunRef
    mission_ref: MissionRef
    plan_ref: ExecutionPlanRef
    plan_intent_sha256: Sha256Digest
    raw_artifact_ref: ArtifactRef
    raw_sha256: Sha256Digest
    manifest_artifact_ref: ArtifactRef
    manifest_sha256: Sha256Digest
    materialization_id: DomainRef
    implementation_version: Literal["m20-e4-materializer@1"] = "m20-e4-materializer@1"
    state: Literal["PUBLISHED"] = "PUBLISHED"
    file_count: int = Field(ge=0)
    verified_entry_count: int = Field(ge=0)
    materialized_bytes: int = Field(ge=0)
    observed_temporary_bytes: int = Field(ge=0)
    observed_write_bytes: int = Field(ge=0)
    observed_duration_seconds: float = Field(ge=0)
    budgets: PreparationBudgets
    tree_sha256: Sha256Digest
    confinement_backend: str
    confinement_version: str
    proven_features: tuple[ConfinementFeature, ...]
    started_at: AwareDatetime
    published_at: AwareDatetime


class MaterializationRejected(TransportModel):
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    code: str = Field(min_length=1, max_length=128)
    retryable: bool = False


type MaterializationResponse = (
    MaterializationEvidence | MaterializationPreflight | MaterializationRejected
)


def parse_materialization_request(data: bytes) -> MaterializeSourceRequest:
    try:
        request = MaterializeSourceRequest.model_validate_json(data)
        if request.message_id != materialization_message_id(request.permit_ref, request.action):
            raise ValueError("materialization request message identity mismatch")
        return request
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid preparation materialization request") from error


def parse_materialization_response(data: bytes) -> MaterializationResponse:
    try:
        value = MaterializationEvidence.model_validate_json(data)
    except (ValidationError, ValueError, TypeError):
        try:
            return MaterializationPreflight.model_validate_json(data)
        except (ValidationError, ValueError, TypeError):
            try:
                return MaterializationRejected.model_validate_json(data)
            except (ValidationError, ValueError, TypeError) as error:
                raise MalformedMessage("invalid preparation materialization response") from error
    return value
