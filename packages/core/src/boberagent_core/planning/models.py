"""M20-D1 value objects only: no persistence, planning pump or execution authority."""

from enum import StrEnum
from typing import Literal, Self

from boberagent_contracts import (
    DomainRef,
    ExecutionPlanRef,
    InteractionRef,
    MissionRef,
    Sha256Digest,
)
from boberagent_contracts._base import FrozenContractModel, NonEmptyStr, SymbolicName
from boberagent_contracts.execution_plan_v2 import ExecutionPlanV2, SensitiveRequirement
from boberagent_contracts.plan_requirements import (
    ExecutionLimits,
    ExecutionLocation,
    ExpectedEvidence,
    ExpectedResult,
    FilesystemConstraints,
    NetworkConstraints,
    PlanDependency,
    PlanSource,
    ResourceRequirement,
    RuntimeRequirement,
    SessionRequirement,
)
from boberagent_contracts.plan_values import (
    BindingValue,
    EntrypointIntent,
    EnvironmentBinding,
    InvocationLayout,
    ParameterBinding,
    PlanTarget,
    TargetRole,
)
from pydantic import AwareDatetime, Field, StrictInt, model_validator

from boberagent_core.inspections.classification_models import (
    SupportClassification,
    SupportClassificationDocument,
)
from boberagent_core.inspections.identity import PoCInspectionRef
from boberagent_core.research.models import PoCCandidateRef, VulnerabilityHypothesisRef


class PlanningAttemptRef(DomainRef):
    """Core-owned planning identity, never an executable CapabilityRunRef."""


class PlanningAttemptLifecycle(StrEnum):
    REQUESTED = "REQUESTED"
    EVALUATING = "EVALUATING"
    WAITING_INPUT = "WAITING_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.INTERRUPTED, self.CANCELLED}


class PlanningDisposition(StrEnum):
    VALID = "VALID"
    REQUIRES_INPUT = "REQUIRES_INPUT"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"


class PlanningInspectionProvenance(FrozenContractModel):
    """Pins exact C2/C3 history; does not read or reclassify it."""

    semantic_profile: Literal["m20-c2-deterministic"] = "m20-c2-deterministic"
    semantic_version: Literal["2"] = "2"
    classification_ref: PoCInspectionRef
    classification_sha256: Sha256Digest
    classification: SupportClassificationDocument

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.classification.classifier_version != "2":
            raise ValueError("new D-v1 planning requires authoritative C3@2")
        return self


class PlanProposal(FrozenContractModel):
    """Partial intent: unresolved values stay explicit, not fabricated final plans."""

    source: PlanSource
    target: PlanTarget | None = None
    entrypoint: EntrypointIntent | None = None
    runtime: RuntimeRequirement | None = None
    invocation: InvocationLayout | None = None
    bindings: tuple[ParameterBinding, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    dependencies: tuple[PlanDependency, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    environment: tuple[EnvironmentBinding, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    sensitive_requirements: tuple[SensitiveRequirement, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    resources: tuple[ResourceRequirement, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    sessions: tuple[SessionRequirement, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    filesystem: FilesystemConstraints | None = None
    network: NetworkConstraints | None = None
    limits: ExecutionLimits | None = None
    expected_evidence: tuple[ExpectedEvidence, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    expected_results: tuple[ExpectedResult, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    unresolved_requirement_ids: tuple[SymbolicName, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )


class PlanningAnswer(FrozenContractModel):
    """Future D6 answer provenance, not Interaction routing or an approval."""

    answer_id: SymbolicName
    interaction_ref: InteractionRef
    planning_attempt_ref: PlanningAttemptRef
    parameter_id: SymbolicName
    operator_id: SymbolicName
    value: BindingValue
    answered_at: AwareDatetime


class PlanProposalRevision(FrozenContractModel):
    planning_attempt_ref: PlanningAttemptRef
    revision_number: StrictInt = Field(ge=1)
    proposal: PlanProposal
    previous_revision_digest: Sha256Digest | None = None
    answers: tuple[PlanningAnswer, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    created_at: AwareDatetime

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.revision_number == 1) != (self.previous_revision_digest is None):
            raise ValueError("revision chain requires an exact previous revision digest")
        if any(answer.planning_attempt_ref != self.planning_attempt_ref for answer in self.answers):
            raise ValueError("answer belongs to another PlanningAttempt")
        return self


class PlanningRequest(FrozenContractModel):
    profile: Literal["m20-d-planning"] = "m20-d-planning"
    profile_version: Literal["1"] = "1"
    policy_profile: SymbolicName = "m20-python-single-target"
    policy_version: NonEmptyStr = "1"
    mission_ref: MissionRef
    hypothesis_ref: VulnerabilityHypothesisRef
    candidate_ref: PoCCandidateRef
    source: PlanSource
    inspection: PlanningInspectionProvenance
    # D3 admission stops before any proposal; existing D1/D2 requests remain unchanged.
    proposal: PlanProposal | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.proposal is not None and self.source != self.proposal.source:
            raise ValueError("proposal must pin the request's exact source")
        return self


class PlanningAttempt(FrozenContractModel):
    planning_attempt_ref: PlanningAttemptRef
    request: PlanningRequest
    lifecycle: PlanningAttemptLifecycle
    disposition: PlanningDisposition | None = None
    revisions: tuple[PlanProposalRevision, ...] = ()
    finalized_plan: ExecutionPlanV2 | None = None
    failure_code: SymbolicName | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    diagnostic_codes: tuple[SymbolicName, ...] = ()

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (
            self.request.inspection.classification.classification
            is SupportClassification.UNSUPPORTED
            and (
                self.disposition is not PlanningDisposition.UNSUPPORTED
                or self.finalized_plan is not None
            )
        ):
            raise ValueError("C3 UNSUPPORTED preserves blockers and forbids a finalized plan")
        if self.lifecycle is PlanningAttemptLifecycle.COMPLETED and self.disposition is None:
            raise ValueError("completed planning requires an explicit disposition")
        if self.disposition is PlanningDisposition.VALID and self.finalized_plan is None:
            raise ValueError("VALID planning requires finalized intent, not permission")
        if (
            self.disposition
            in (
                PlanningDisposition.UNSUPPORTED,
                PlanningDisposition.REQUIRES_INPUT,
                PlanningDisposition.INVALID,
            )
            and self.finalized_plan is not None
        ):
            raise ValueError("non-valid disposition cannot carry finalized intent")
        if self.finalized_plan is not None and (
            self.finalized_plan.mission_ref != self.request.mission_ref
            or self.finalized_plan.source != self.request.source
        ):
            raise ValueError("finalized intent must preserve request Mission and exact source")
        if tuple(item.revision_number for item in self.revisions) != tuple(
            range(1, len(self.revisions) + 1)
        ) or any(item.planning_attempt_ref != self.planning_attempt_ref for item in self.revisions):
            raise ValueError("revisions must be ordered, contiguous and owned by this attempt")
        return self


class PlanValidationStatus(StrEnum):
    VALID = "VALID"
    REQUIRES_INPUT = "REQUIRES_INPUT"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"


class PlanValidationReasonCode(StrEnum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"
    ENTRYPOINT_INVALID = "ENTRYPOINT_INVALID"
    ENTRYPOINT_SELECTION_REQUIRED = "ENTRYPOINT_SELECTION_REQUIRED"
    INVOCATION_LAYOUT_INVALID = "INVOCATION_LAYOUT_INVALID"
    BINDING_MISSING = "BINDING_MISSING"
    BINDING_TYPE_MISMATCH = "BINDING_TYPE_MISMATCH"
    DEPENDENCY_UNSUPPORTED = "DEPENDENCY_UNSUPPORTED"
    FILESYSTEM_UNSUPPORTED = "FILESYSTEM_UNSUPPORTED"
    NETWORK_UNSUPPORTED = "NETWORK_UNSUPPORTED"
    LIMITS_REQUIRED = "LIMITS_REQUIRED"
    ASSISTANCE_REQUIRED = "ASSISTANCE_REQUIRED"
    NONINTERACTIVE_REQUIRED = "NONINTERACTIVE_REQUIRED"
    USER_SPACE_REQUIRED = "USER_SPACE_REQUIRED"
    ATTACKER_SIDE_REQUIRED = "ATTACKER_SIDE_REQUIRED"
    CONSISTENT_INTENT = "CONSISTENT_INTENT"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    MISSION_MISMATCH = "MISSION_MISMATCH"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    TARGET_ROLE_MISMATCH = "TARGET_ROLE_MISMATCH"
    UNRESOLVED_BINDING = "UNRESOLVED_BINDING"
    INVOCATION_LAYOUT_REQUIRED = "INVOCATION_LAYOUT_REQUIRED"
    C3_BLOCKER = "C3_BLOCKER"
    UNSUPPORTED_RUNTIME = "UNSUPPORTED_RUNTIME"
    UNKNOWN_CRITICAL_EFFECT = "UNKNOWN_CRITICAL_EFFECT"
    PREREQUISITE_UNAVAILABLE = "PREREQUISITE_UNAVAILABLE"


class PlanValidationReason(FrozenContractModel):
    code: PlanValidationReasonCode
    evidence_refs: tuple[SymbolicName, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )


class PlanDecisionBinding(FrozenContractModel):
    """Assessment identity, not credentials or permission for an Execution Node."""

    execution_plan_ref: ExecutionPlanRef
    intent_sha256: Sha256Digest
    mission_ref: MissionRef
    scope_sha256: Sha256Digest


class PlanValidation(PlanDecisionBinding):
    validation_profile: SymbolicName
    validation_version: NonEmptyStr
    status: PlanValidationStatus
    reasons: tuple[PlanValidationReason, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )
    assessed_at: AwareDatetime


class PlanPolicyDecision(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class PlanPolicyAssessment(PlanDecisionBinding):
    policy_profile: SymbolicName
    policy_version: NonEmptyStr
    # D5 pins exact profile content; optional for historical D2 policy records.
    policy_sha256: Sha256Digest | None = None
    # Separate checker identity; historical D2 records predate the D5 evaluator.
    evaluator_profile: SymbolicName | None = None
    evaluator_version: NonEmptyStr | None = None
    decision: PlanPolicyDecision
    reason_codes: tuple[SymbolicName, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )
    assessed_at: AwareDatetime


class OperatorPlanApproval(PlanDecisionBinding):
    """Deliberate exact-intent human decision; never a Node execution credential."""

    policy_profile: SymbolicName
    policy_version: NonEmptyStr
    decision: Literal["APPROVE", "REJECT"]
    operator_id: SymbolicName
    decided_at: AwareDatetime


class InitialPlanPolicyProfile(FrozenContractModel):
    """Narrow positive-profile definition only. No evaluator or policy language."""

    profile: Literal["m20-python-single-target"] = "m20-python-single-target"
    version: Literal["1"] = "1"
    single_mission_target: Literal[True] = True
    runtime_kind: Literal["python"] = "python"
    platform: Literal["LINUX"] = "LINUX"
    platform_variant: Literal["kali"] = "kali"
    execution_location: Literal[ExecutionLocation.ATTACKER_NODE] = ExecutionLocation.ATTACKER_NODE
    user_space: Literal[True] = True
    noninteractive: Literal[True] = True
    source_available: Literal[True] = True
    explicit_endpoint: Literal[True] = True
    explicit_network_constraints: Literal[True] = True
    broad_effects_allowed: Literal[False] = False
    destructive_effects_allowed: Literal[False] = False
    critical_unknowns_allowed: Literal[False] = False
    allowed_target_roles: tuple[
        Literal[TargetRole.HOST, TargetRole.IP, TargetRole.URL, TargetRole.SERVICE_ENDPOINT], ...
    ] = Field(
        default=(TargetRole.HOST, TargetRole.IP, TargetRole.URL, TargetRole.SERVICE_ENDPOINT),
        min_length=1,
        json_schema_extra={"collection_semantics": "set"},
    )
    maximum_limits: ExecutionLimits


class DecisionContext(FrozenContractModel):
    """Current semantic decision inputs; no connection, runtime path or secret material."""

    mission_ref: MissionRef
    intent_sha256: Sha256Digest
    scope_sha256: Sha256Digest
    classification_sha256: Sha256Digest
    validation_profile: SymbolicName
    validation_version: NonEmptyStr
    policy: InitialPlanPolicyProfile
    # Digest of reference/status metadata only, never sensitive values or their hashes.
    prerequisite_state_sha256: Sha256Digest | None = None
