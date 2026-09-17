"""Core-owned domain snapshots kept separate from persistence ORM rows."""

from enum import StrEnum
from typing import Annotated

from boberagent_contracts import (
    ArtifactDescriptor,
    AssetRef,
    JsonObject,
    MissionRef,
    Observation,
    ObservationRef,
    ServiceRef,
    WorkflowRunRef,
)
from boberagent_contracts.refs import DomainRef
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

type ExtensibleStatus = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type AssetKind = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type GoalType = Annotated[str, StringConstraints(min_length=1, max_length=255)]


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


class WorkflowStatus(StrEnum):
    """Minimal persisted Workflow lifecycle from the workflow specification."""

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXHAUSTED = "EXHAUSTED"


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
    """Persisted Workflow identity and lifecycle metadata only."""

    workflow_run_ref: WorkflowRunRef
    mission_ref: MissionRef
    procedure_ref: str = Field(min_length=1, max_length=255)
    status: WorkflowStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime


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
