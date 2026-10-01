"""Core-private E2 request, history and admission projection; no execution authority."""

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from boberagent_contracts import (
    CapabilityRunRef,
    ExecutionPlanRef,
    MissionRef,
    PlanDecisionRef,
    PreparationPermit,
    PreparationPermitRef,
    RuntimePreparationRef,
    Sha256Digest,
)
from boberagent_contracts._base import FrozenContractModel, NonEmptyStr, SymbolicName
from boberagent_contracts.plan_requirements import PlanSource
from boberagent_contracts.runtime_preparation import (
    ConfinementFeature,
    PreparationAction,
    PreparationBudgets,
    PreparationNodeId,
    RuntimePreparationSpec,
)
from pydantic import AwareDatetime, Field, model_validator

from boberagent_core.capabilities.models import ProviderAvailability
from boberagent_core.inspections.identity import PoCInspectionRef
from boberagent_core.planning.models import PlanningAttemptRef, PlanPolicyDecision


class PreparationLifecycle(StrEnum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    AWAITING_ARTIFACT = "AWAITING_ARTIFACT"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.REJECTED,
            self.FAILED,
            self.INTERRUPTED,
            self.CANCELLED,
        }


class PreparationDisposition(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"


class PreparationAdmissionReason(StrEnum):
    PLAN_INVALID_OR_STALE = "PLAN_INVALID_OR_STALE"
    VALIDATION_UNAVAILABLE = "VALIDATION_UNAVAILABLE"
    POLICY_NOT_EVALUATED = "POLICY_NOT_EVALUATED"
    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    SOURCE_PROVENANCE_MISMATCH = "SOURCE_PROVENANCE_MISMATCH"
    TARGET_SCOPE_STALE = "TARGET_SCOPE_STALE"
    NODE_SELECTION_INVALID = "NODE_SELECTION_INVALID"
    PROVIDER_SELECTION_INVALID = "PROVIDER_SELECTION_INVALID"
    PREPARATION_PROFILE_UNSUPPORTED = "PREPARATION_PROFILE_UNSUPPORTED"
    DEPENDENCY_REQUIREMENT_UNSUPPORTED = "DEPENDENCY_REQUIREMENT_UNSUPPORTED"
    SECRET_REQUIREMENT_UNSUPPORTED = "SECRET_REQUIREMENT_UNSUPPORTED"
    RUNTIME_REQUIREMENT_UNSUPPORTED = "RUNTIME_REQUIREMENT_UNSUPPORTED"
    PREPARATION_NETWORK_UNSUPPORTED = "PREPARATION_NETWORK_UNSUPPORTED"
    CONFINEMENT_REQUIREMENT_INVALID = "CONFINEMENT_REQUIREMENT_INVALID"
    PREPARATION_BUDGET_INVALID = "PREPARATION_BUDGET_INVALID"
    PREPARATION_ACTION_UNSUPPORTED = "PREPARATION_ACTION_UNSUPPORTED"


class PreparationRequest(FrozenContractModel):
    """Only selection/configuration is caller-controlled; no D decision or source copies."""

    mission_ref: MissionRef
    plan_ref: ExecutionPlanRef
    node_id: PreparationNodeId
    provider_id: UUID
    profile_id: SymbolicName
    profile_version: NonEmptyStr
    budgets: PreparationBudgets | None
    confinement_features: tuple[ConfinementFeature, ...]
    actions: tuple[PreparationAction, ...]


class PreparationContext(FrozenContractModel):
    """Exact authoritative identity snapshot; changes create a new fingerprint/history."""

    request: PreparationRequest
    planning_attempt_ref: PlanningAttemptRef
    plan_intent_sha256: Sha256Digest
    source: PlanSource
    semantic_inspection_ref: PoCInspectionRef
    semantic_sha256: Sha256Digest
    classification_inspection_ref: PoCInspectionRef
    classification_sha256: Sha256Digest
    validation_decision_ref: PlanDecisionRef | None
    validation_sha256: Sha256Digest | None
    policy_decision_ref: PlanDecisionRef | None
    policy_context_sha256: Sha256Digest | None
    policy_sha256: Sha256Digest | None
    policy_decision: PlanPolicyDecision | None
    approval_decision_ref: PlanDecisionRef | None
    provider_version: NonEmptyStr | None
    provider_availability: ProviderAvailability | None
    provider_node_lifecycle: str | None
    profile_sha256: Sha256Digest
    manifest_size_bytes: int | None = Field(default=None, ge=0)


class PreparationAttempt(FrozenContractModel):
    """Durable request and immutable determination; no CapabilityRun row exists in E2."""

    schema_version: Literal["runtime-preparation-attempt-v1"] = "runtime-preparation-attempt-v1"
    preparation_ref: RuntimePreparationRef
    context: PreparationContext
    request_fingerprint: Sha256Digest
    lifecycle: PreparationLifecycle
    disposition: PreparationDisposition
    reason_code: PreparationAdmissionReason | None
    reserved_run_ref: CapabilityRunRef | None
    spec: RuntimePreparationSpec | None
    permit_ref: PreparationPermitRef | None
    revision: int = Field(ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    terminal_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.lifecycle is PreparationLifecycle.REQUESTED:
            if (
                self.disposition is not PreparationDisposition.ELIGIBLE
                or self.reason_code is not None
                or self.reserved_run_ref is None
                or self.spec is None
                or self.permit_ref is None
                or self.terminal_at is not None
            ):
                raise ValueError("eligible request needs exact spec, RunRef and permit binding")
        elif self.lifecycle is PreparationLifecycle.REJECTED and (
            self.disposition is not PreparationDisposition.REJECTED
            or self.reason_code is None
            or self.reserved_run_ref is not None
            or self.spec is not None
            or self.permit_ref is not None
            or self.terminal_at is None
        ):
            raise ValueError("rejected request cannot reserve a Run or permit")
        if self.updated_at < self.created_at or (
            self.terminal_at is not None and self.terminal_at != self.updated_at
        ):
            raise ValueError("preparation timestamps are inconsistent")
        if self.spec is not None and (
            self.spec.preparation_ref != self.preparation_ref
            or self.spec.plan_ref != self.context.request.plan_ref
            or self.spec.plan_intent_sha256 != self.context.plan_intent_sha256
        ):
            raise ValueError("preparation spec does not bind the attempt")
        return self


class PreparationAdmission(FrozenContractModel):
    attempt: PreparationAttempt
    permit: PreparationPermit | None
    current_applicable: bool
    current_reason: PreparationAdmissionReason | None = None
    execution_readiness: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
    execution_authorization: Literal["NONE"] = "NONE"

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.attempt.permit_ref is not None) != (self.permit is not None):
            raise ValueError("permit presence must match durable attempt history")
        if self.permit is not None and (
            self.permit.permit_ref != self.attempt.permit_ref
            or self.permit.spec != self.attempt.spec
            or self.permit.run_ref != self.attempt.reserved_run_ref
        ):
            raise ValueError("permit and attempt do not bind")
        return self
