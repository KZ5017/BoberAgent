"""Core-owned domain snapshots kept separate from persistence ORM rows."""

from enum import StrEnum
from typing import Annotated, Self

from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    AssetRef,
    CapabilityId,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    CredentialRef,
    IdentityRef,
    JsonObject,
    MissionRef,
    Observation,
    ObservationRef,
    OperationName,
    SecretRef,
    ServiceRef,
    WorkflowRunRef,
)
from boberagent_contracts.refs import DomainRef
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

type ExtensibleStatus = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type AssetKind = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type GoalType = Annotated[str, StringConstraints(min_length=1, max_length=255)]
type CredentialKind = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type SecretKind = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type SecretRole = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class GoalRef(DomainRef):
    """Core-owned Goal identity; Goal is not a Capability Contract object."""


class CoreModel(BaseModel):
    """Immutable validated snapshot returned by Core repositories."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class MaterializationStatus(StrEnum):
    """Observation processing status defined by the World State model."""

    PENDING = "PENDING"
    MATERIALIZED = "MATERIALIZED"
    PARTIALLY_MATERIALIZED = "PARTIALLY_MATERIALIZED"
    UNSUPPORTED = "UNSUPPORTED"
    REJECTED = "REJECTED"


class ArtifactContentState(StrEnum):
    """Core-owned availability state, separate from Contract metadata."""

    METADATA_ONLY = "METADATA_ONLY"
    RECEIVING = "RECEIVING"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"


class SecretStatus(StrEnum):
    """Small Core-owned lifecycle for canonical sensitive values."""

    AVAILABLE = "AVAILABLE"
    REVOKED = "REVOKED"
    UNAVAILABLE = "UNAVAILABLE"


class CredentialStatus(StrEnum):
    """Assessment lifecycle for reusable authentication context."""

    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class SecretMetadata(CoreModel):
    """Inspectable Secret metadata that intentionally excludes the value."""

    secret_ref: SecretRef
    mission_ref: MissionRef
    secret_type: SecretKind
    status: SecretStatus
    created_at: AwareDatetime
    created_by_run_ref: CapabilityRunRef | None = None
    source_observation_ref: ObservationRef | None = None
    source_artifact_refs: tuple[ArtifactRef, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)


class CredentialSecretBinding(CoreModel):
    """Name the operational role of one referenced sensitive value."""

    role: SecretRole
    secret_ref: SecretRef


class Credential(CoreModel):
    """Mission-owned authentication identity/context referencing canonical Secrets."""

    credential_ref: CredentialRef
    mission_ref: MissionRef
    credential_type: CredentialKind
    username: str | None = Field(default=None, min_length=1, max_length=255)
    identity_ref: IdentityRef | None = None
    secrets: tuple[CredentialSecretBinding, ...] = Field(min_length=1)
    scope_refs: tuple[DomainRef, ...] = ()
    status: CredentialStatus
    source_observation_refs: tuple[ObservationRef, ...] = ()
    source_artifact_refs: tuple[ArtifactRef, ...] = ()
    created_at: AwareDatetime
    updated_at: AwareDatetime
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_unique_secret_roles(self) -> Self:
        roles = [binding.role for binding in self.secrets]
        if len(roles) != len(set(roles)):
            raise ValueError("Credential secret roles must be unique")
        return self


class SecretAccessRecord(CoreModel):
    """Non-sensitive audit metadata for an explicit Secret resolution."""

    access_id: int
    secret_ref: SecretRef
    mission_ref: MissionRef
    run_ref: CapabilityRunRef | None = None
    accessor: str = Field(min_length=1, max_length=32)
    purpose: str = Field(min_length=1, max_length=255)
    accessed_at: AwareDatetime


class WorkflowStatus(StrEnum):
    """Minimal persisted Workflow lifecycle from the workflow specification."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXHAUSTED = "EXHAUSTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.EXHAUSTED,
        }


class WorkflowStepStatus(StrEnum):
    """Durable state of one deterministic sequential Workflow step."""

    PENDING = "PENDING"
    PREPARED = "PREPARED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            WorkflowStepStatus.COMPLETED,
            WorkflowStepStatus.FAILED,
            WorkflowStepStatus.CANCELLED,
        }


class WorkflowStepSuccessPolicy(StrEnum):
    """Explicit M11 semantic outcomes that permit sequential progression."""

    SUCCESS_ONLY = "SUCCESS_ONLY"
    SUCCESS_OR_NEGATIVE = "SUCCESS_OR_NEGATIVE"

    def accepts(self, outcome: CapabilityOutcomeCategory) -> bool:
        if outcome is CapabilityOutcomeCategory.SUCCESS:
            return True
        return (
            self is WorkflowStepSuccessPolicy.SUCCESS_OR_NEGATIVE
            and outcome is CapabilityOutcomeCategory.NEGATIVE
        )


class WorkflowStepDefinition(CoreModel):
    """Immutable static intent for one ordered Capability invocation."""

    step_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
    capability_id: CapabilityId
    operation: OperationName
    inputs: JsonObject = Field(default_factory=dict)
    credential_refs: tuple[CredentialRef, ...] = ()
    secret_refs: tuple[SecretRef, ...] = ()
    success_policy: WorkflowStepSuccessPolicy = WorkflowStepSuccessPolicy.SUCCESS_ONLY

    @model_validator(mode="after")
    def require_unique_authorization_refs(self) -> Self:
        if len(self.credential_refs) != len(set(self.credential_refs)):
            raise ValueError("Workflow step CredentialRefs must be unique")
        if len(self.secret_refs) != len(set(self.secret_refs)):
            raise ValueError("Workflow step SecretRefs must be unique")
        return self


class WorkflowDefinition(CoreModel):
    """Immutable, versioned, sequential execution intent."""

    definition_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,254}$")
    version: str = Field(min_length=1, max_length=64)
    steps: tuple[WorkflowStepDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_step_ids(self) -> Self:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Workflow step identifiers must be unique")
        return self

    @property
    def procedure_ref(self) -> str:
        return f"{self.definition_id}@{self.version}"


class GoalStatus(StrEnum):
    """Minimal persisted Goal lifecycle from the workflow specification."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    BLOCKED = "BLOCKED"
    IMPOSSIBLE = "IMPOSSIBLE"
    ABANDONED = "ABANDONED"


class Mission(CoreModel):
    """Minimal persisted Mission state for the bootstrap."""

    mission_ref: MissionRef
    status: ExtensibleStatus
    created_at: AwareDatetime
    name: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: JsonObject = Field(default_factory=dict)


class Asset(CoreModel):
    """Scoped assessment asset owned by one Mission."""

    asset_ref: AssetRef
    mission_ref: MissionRef
    kind: AssetKind
    primary_address: str = Field(min_length=1, max_length=255)
    created_at: AwareDatetime
    metadata: JsonObject = Field(default_factory=dict)


class StoredObservation(CoreModel):
    """Immutable Observation plus independently mutable processing metadata."""

    observation: Observation
    materialization_status: MaterializationStatus
    materialization_error: str | None = None


class StoredArtifact(CoreModel):
    """Artifact metadata plus Core-owned content availability state."""

    descriptor: ArtifactDescriptor
    content_state: ArtifactContentState
    received_bytes: int = Field(ge=0)
    sync_error: str | None = None

    @property
    def content_available(self) -> bool:
        return self.content_state is ArtifactContentState.AVAILABLE


class Service(CoreModel):
    """Current materialized service endpoint state."""

    service_ref: ServiceRef
    asset_ref: AssetRef
    transport: str
    port: int = Field(ge=1, le=65535)
    state: str
    service: str | None = None
    product: str | None = None
    version: str | None = None
    first_observed_at: AwareDatetime
    last_observed_at: AwareDatetime
    current_observation_ref: ObservationRef
    provenance_refs: tuple[ObservationRef, ...]


class WorkflowRun(CoreModel):
    """One durable execution of an immutable Workflow definition."""

    workflow_run_ref: WorkflowRunRef
    mission_ref: MissionRef
    procedure_ref: str = Field(min_length=1, max_length=255)
    status: WorkflowStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    definition: WorkflowDefinition | None = None
    failure_reason: str | None = Field(default=None, min_length=1, max_length=2048)


class WorkflowStepRun(CoreModel):
    """Durable execution state and CapabilityRun mapping for one Workflow step."""

    workflow_run_ref: WorkflowRunRef
    step_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
    position: int = Field(ge=0)
    definition: WorkflowStepDefinition
    status: WorkflowStepStatus
    capability_run_ref: CapabilityRunRef | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    failure_reason: str | None = Field(default=None, min_length=1, max_length=2048)


class WorkflowExecution(CoreModel):
    """Read model combining a Workflow Run and its ordered Step Runs."""

    run: WorkflowRun
    steps: tuple[WorkflowStepRun, ...]


class Goal(CoreModel):
    """Persisted Goal metadata without evaluation behavior."""

    goal_ref: GoalRef
    mission_ref: MissionRef
    workflow_run_ref: WorkflowRunRef | None = None
    goal_type: GoalType
    parameters: JsonObject = Field(default_factory=dict)
    status: GoalStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
