"""Validated snapshots for node-owned runtime metadata."""

from enum import StrEnum

from boberagent_contracts import (
    ArtifactDescriptor,
    CapabilityRunRef,
    CapabilityRunStatus,
    Event,
    JsonObject,
    MissionRef,
    ResourceDescriptor,
    SessionDescriptor,
    WorkflowRunRef,
)
from boberagent_sdk import WorkspaceIsolation, WorkspaceRef
from pydantic import AwareDatetime, BaseModel, ConfigDict


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ProcessState(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    EXITED = "EXITED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"
    LOST = "LOST"


class WorkspaceState(StrEnum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    RETAINED = "RETAINED"
    CLEANUP_PENDING = "CLEANUP_PENDING"
    REMOVED = "REMOVED"


class ArtifactSyncState(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    SYNC_PENDING = "SYNC_PENDING"
    SYNCED = "SYNCED"
    SYNC_FAILED = "SYNC_FAILED"


class DeliveryState(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"


class ResourceRuntimeState(StrEnum):
    CREATING = "CREATING"
    READY = "READY"
    FAILED = "FAILED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    LOST = "LOST"


class SessionRuntimeState(StrEnum):
    CREATING = "CREATING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    LOST = "LOST"


class RunRecord(RuntimeModel):
    run_ref: CapabilityRunRef
    mission_ref: MissionRef
    capability_id: str
    operation: str
    status: CapabilityRunStatus
    created_at: AwareDatetime
    parent_run_ref: CapabilityRunRef | None = None
    workflow_run_ref: WorkflowRunRef | None = None
    invocation_fingerprint: str | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error_code: str | None = None


class ProcessRecord(RuntimeModel):
    process_id: str
    run_ref: CapabilityRunRef
    tool: str
    state: ProcessState
    argument_count: int
    pid: int | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    exit_code: int | None = None


class WorkspaceRecord(RuntimeModel):
    workspace_ref: WorkspaceRef
    owner_ref: str
    purpose: str
    isolation: WorkspaceIsolation
    local_path: str
    state: WorkspaceState
    created_at: AwareDatetime


class SpoolArtifactRecord(RuntimeModel):
    descriptor: ArtifactDescriptor
    local_path: str
    sync_state: ArtifactSyncState
    sync_attempt_count: int = 0
    last_sync_attempt_at: AwareDatetime | None = None
    sync_error: str | None = None


class EventOutboxRecord(RuntimeModel):
    sequence: int
    event: Event
    delivery_state: DeliveryState
    created_at: AwareDatetime


class ResultOutboxRecord(RuntimeModel):
    sequence: int
    run_ref: CapabilityRunRef
    result_json: JsonObject
    delivery_state: DeliveryState
    created_at: AwareDatetime


class ResourceRuntimeRecord(RuntimeModel):
    descriptor: ResourceDescriptor
    updated_at: AwareDatetime
    last_activity_at: AwareDatetime


class SessionRuntimeRecord(RuntimeModel):
    descriptor: SessionDescriptor
    updated_at: AwareDatetime
    last_activity_at: AwareDatetime
