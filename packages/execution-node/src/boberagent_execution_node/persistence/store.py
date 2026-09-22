"""Explicit repository facade for node-owned runtime state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import (
    AccessContextRef,
    AccessMode,
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityResult,
    CapabilityRunRef,
    CapabilityRunStatus,
    DomainRef,
    Event,
    EventRef,
    IdentityRef,
    InteractionLifecycle,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    JsonObject,
    MissionRef,
    ResourceDescriptor,
    ResourceRef,
    SessionDescriptor,
    SessionRef,
    StorageRef,
    WorkflowRunRef,
    validate_interaction_response,
)
from boberagent_sdk import WorkspaceIsolation, WorkspaceRef
from pydantic import TypeAdapter
from sqlalchemy import func, select

from .database import RuntimeDatabase
from .models import (
    ArtifactSyncState,
    DeliveryState,
    EventOutboxRecord,
    InteractionRuntimeRecord,
    ProcessRecord,
    ProcessState,
    ResourceRuntimeRecord,
    ResourceRuntimeState,
    ResultOutboxRecord,
    RunRecord,
    SessionRuntimeRecord,
    SessionRuntimeState,
    SpoolArtifactRecord,
    WorkspaceRecord,
    WorkspaceState,
)
from .orm import (
    ArtifactRow,
    EventOutboxRow,
    ProcessRow,
    ResultOutboxRow,
    RunRow,
    RuntimeInteractionRow,
    RuntimeResourceRow,
    RuntimeSessionRow,
    WorkspaceRow,
)

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class RuntimeStore:
    """Keep SQLAlchemy details behind node-owned persistence operations."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self._database = database

    def add_run(self, record: RunRecord) -> None:
        with self._database.transaction() as session:
            session.add(
                RunRow(
                    run_id=str(record.run_ref),
                    mission_id=str(record.mission_ref),
                    capability_id=record.capability_id,
                    operation=record.operation,
                    status=record.status.value,
                    parent_run_id=(
                        None if record.parent_run_ref is None else str(record.parent_run_ref)
                    ),
                    workflow_run_id=(
                        None if record.workflow_run_ref is None else str(record.workflow_run_ref)
                    ),
                    invocation_fingerprint=record.invocation_fingerprint,
                    created_at=record.created_at,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    error_code=record.error_code,
                )
            )

    def get_run(self, run_ref: CapabilityRunRef) -> RunRecord | None:
        with self._database.transaction() as session:
            row = session.get(RunRow, str(run_ref))
            return None if row is None else _run_record(row)

    def update_run(
        self,
        run_ref: CapabilityRunRef,
        status: CapabilityRunStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_code: str | None = None,
    ) -> None:
        with self._database.transaction() as session:
            row = session.get(RunRow, str(run_ref))
            if row is None:
                raise KeyError(f"unknown local CapabilityRun: {run_ref}")
            row.status = status.value
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            row.error_code = error_code

    def begin_interaction(self, request: InteractionRequest) -> InteractionRuntimeRecord:
        """Persist a request before atomically moving its Run to WAITING_INPUT."""

        request_json = _json_object_adapter.validate_python(request.model_dump(mode="json"))
        with self._database.transaction() as session:
            run = session.get(RunRow, str(request.run_ref))
            if run is None:
                raise KeyError(f"unknown local CapabilityRun: {request.run_ref}")
            if run.mission_id != str(request.mission_ref):
                raise ValueError("Interaction Mission does not match its CapabilityRun")
            if run.workflow_run_id != (
                None if request.workflow_run_ref is None else str(request.workflow_run_ref)
            ):
                raise ValueError("Interaction Workflow does not match its CapabilityRun")
            existing = session.get(RuntimeInteractionRow, str(request.interaction_id))
            if existing is not None:
                if existing.request_json != request_json:
                    raise ValueError(f"Interaction identity collision: {request.interaction_id}")
                return _interaction_record(existing)
            if CapabilityRunStatus(run.status) is not CapabilityRunStatus.RUNNING:
                raise ValueError("Interaction can only be requested by a RUNNING CapabilityRun")
            row = RuntimeInteractionRow(
                interaction_id=str(request.interaction_id),
                run_id=str(request.run_ref),
                mission_id=str(request.mission_ref),
                workflow_run_id=(
                    None if request.workflow_run_ref is None else str(request.workflow_run_ref)
                ),
                state=InteractionLifecycle.REQUESTED.value,
                request_json=request_json,
                response_json=None,
                requested_at=request.requested_at,
                responded_at=None,
                cancelled_at=None,
                cancellation_reason=None,
            )
            session.add(row)
            session.flush()
            run.status = CapabilityRunStatus.WAITING_INPUT.value
            return _interaction_record(row)

    def get_interaction(self, interaction_ref: InteractionRef) -> InteractionRuntimeRecord | None:
        with self._database.transaction() as session:
            row = session.get(RuntimeInteractionRow, str(interaction_ref))
            return None if row is None else _interaction_record(row)

    def list_interactions_for_run(
        self, run_ref: CapabilityRunRef
    ) -> tuple[InteractionRuntimeRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(RuntimeInteractionRow)
                .where(RuntimeInteractionRow.run_id == str(run_ref))
                .order_by(RuntimeInteractionRow.requested_at, RuntimeInteractionRow.interaction_id)
            )
            return tuple(_interaction_record(row) for row in rows)

    def accept_interaction_response(
        self, response: InteractionResponse
    ) -> tuple[InteractionRuntimeRecord, bool]:
        """Durably accept once and restore RUNNING; return whether this was a duplicate."""

        response_json = _json_object_adapter.validate_python(response.model_dump(mode="json"))
        with self._database.transaction() as session:
            row = session.get(RuntimeInteractionRow, str(response.interaction_ref))
            if row is None:
                raise KeyError(f"unknown Interaction: {response.interaction_ref}")
            request = InteractionRequest.model_validate(row.request_json)
            validate_interaction_response(request, response)
            state = InteractionLifecycle(row.state)
            if state is InteractionLifecycle.ANSWERED:
                if row.response_json != response_json:
                    raise ValueError("Interaction already has a different immutable response")
                return _interaction_record(row), True
            if state is not InteractionLifecycle.REQUESTED:
                raise ValueError(f"Interaction is no longer answerable: {state.value}")
            run = session.get(RunRow, row.run_id)
            if (
                run is None
                or CapabilityRunStatus(run.status) is not CapabilityRunStatus.WAITING_INPUT
            ):
                raise ValueError("Interaction CapabilityRun is no longer waiting for input")
            row.response_json = response_json
            row.responded_at = response.responded_at
            row.state = InteractionLifecycle.ANSWERED.value
            run.status = CapabilityRunStatus.RUNNING.value
            session.flush()
            return _interaction_record(row), False

    def cancel_interactions_for_run(
        self,
        run_ref: CapabilityRunRef,
        *,
        cancelled_at: datetime,
        reason: str,
    ) -> tuple[InteractionRuntimeRecord, ...]:
        with self._database.transaction() as session:
            rows = tuple(
                session.scalars(
                    select(RuntimeInteractionRow).where(
                        RuntimeInteractionRow.run_id == str(run_ref),
                        RuntimeInteractionRow.state == InteractionLifecycle.REQUESTED.value,
                    )
                )
            )
            for row in rows:
                row.state = InteractionLifecycle.CANCELLED.value
                row.cancelled_at = cancelled_at
                row.cancellation_reason = reason
            session.flush()
            return tuple(_interaction_record(row) for row in rows)

    def add_process(self, record: ProcessRecord) -> None:
        with self._database.transaction() as session:
            session.add(
                ProcessRow(
                    process_id=record.process_id,
                    run_id=str(record.run_ref),
                    tool=record.tool,
                    state=record.state.value,
                    argument_count=record.argument_count,
                    pid=record.pid,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    exit_code=record.exit_code,
                )
            )

    def update_process(
        self,
        process_id: str,
        state: ProcessState,
        *,
        pid: int | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        exit_code: int | None = None,
    ) -> None:
        with self._database.transaction() as session:
            row = session.get(ProcessRow, process_id)
            if row is None:
                raise KeyError(f"unknown managed process: {process_id}")
            row.state = state.value
            if pid is not None:
                row.pid = pid
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            row.exit_code = exit_code

    def get_process(self, process_id: str) -> ProcessRecord | None:
        with self._database.transaction() as session:
            row = session.get(ProcessRow, process_id)
            return None if row is None else _process_record(row)

    def list_processes_for_run(self, run_ref: CapabilityRunRef) -> tuple[ProcessRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(ProcessRow)
                .where(ProcessRow.run_id == str(run_ref))
                .order_by(ProcessRow.process_id)
            )
            return tuple(_process_record(row) for row in rows)

    def add_workspace(self, record: WorkspaceRecord) -> None:
        with self._database.transaction() as session:
            session.add(
                WorkspaceRow(
                    workspace_id=str(record.workspace_ref),
                    owner_ref=record.owner_ref,
                    purpose=record.purpose,
                    isolation=record.isolation.value,
                    local_path=record.local_path,
                    state=record.state.value,
                    created_at=record.created_at,
                )
            )

    def get_workspace(self, workspace_ref: WorkspaceRef) -> WorkspaceRecord | None:
        with self._database.transaction() as session:
            row = session.get(WorkspaceRow, str(workspace_ref))
            return None if row is None else _workspace_record(row)

    def list_workspaces_for_owner(self, owner_ref: str) -> tuple[WorkspaceRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(WorkspaceRow)
                .where(WorkspaceRow.owner_ref == owner_ref)
                .order_by(WorkspaceRow.workspace_id)
            )
            return tuple(_workspace_record(row) for row in rows)

    def set_workspace_state(self, workspace_ref: WorkspaceRef, state: WorkspaceState) -> None:
        with self._database.transaction() as session:
            row = session.get(WorkspaceRow, str(workspace_ref))
            if row is None:
                raise KeyError(f"unknown Workspace: {workspace_ref}")
            row.state = state.value

    def add_resource(self, record: ResourceRuntimeRecord) -> None:
        descriptor = record.descriptor
        with self._database.transaction() as session:
            session.add(
                RuntimeResourceRow(
                    resource_id=str(descriptor.resource_id),
                    resource_type=descriptor.resource_type,
                    provider=descriptor.provider,
                    state=descriptor.state,
                    owner_ref=str(descriptor.owner_ref),
                    created_by_run=str(descriptor.created_by_run),
                    created_at=descriptor.created_at,
                    updated_at=record.updated_at,
                    last_activity_at=record.last_activity_at,
                    access_modes_json=[mode.value for mode in descriptor.access_modes],
                    expires_at=descriptor.expires_at,
                    lifecycle_metadata_json=deepcopy(descriptor.lifecycle_metadata),
                )
            )

    def get_resource(self, resource_ref: ResourceRef) -> ResourceRuntimeRecord | None:
        with self._database.transaction() as session:
            row = session.get(RuntimeResourceRow, str(resource_ref))
            return None if row is None else _resource_record(row)

    def list_resources(self) -> tuple[ResourceRuntimeRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(RuntimeResourceRow).order_by(RuntimeResourceRow.resource_id)
            )
            return tuple(_resource_record(row) for row in rows)

    def update_resource_state(
        self,
        resource_ref: ResourceRef,
        state: ResourceRuntimeState,
        occurred_at: datetime,
        *,
        lifecycle_metadata: JsonObject | None = None,
    ) -> None:
        with self._database.transaction() as session:
            row = session.get(RuntimeResourceRow, str(resource_ref))
            if row is None:
                raise KeyError(f"unknown Resource: {resource_ref}")
            row.state = state.value
            row.updated_at = occurred_at
            row.last_activity_at = occurred_at
            if lifecycle_metadata is not None:
                row.lifecycle_metadata_json = deepcopy(lifecycle_metadata)

    def touch_resource(self, resource_ref: ResourceRef, occurred_at: datetime) -> None:
        with self._database.transaction() as session:
            row = session.get(RuntimeResourceRow, str(resource_ref))
            if row is None:
                raise KeyError(f"unknown Resource: {resource_ref}")
            row.updated_at = occurred_at
            row.last_activity_at = occurred_at

    def add_session(self, record: SessionRuntimeRecord) -> None:
        descriptor = record.descriptor
        with self._database.transaction() as session:
            session.add(
                RuntimeSessionRow(
                    session_id=str(descriptor.session_id),
                    session_type=descriptor.session_type,
                    provider=descriptor.provider,
                    state=descriptor.state,
                    owner_ref=str(descriptor.owner_ref),
                    created_by_run=str(descriptor.created_by_run),
                    created_at=descriptor.created_at,
                    updated_at=record.updated_at,
                    last_activity_at=record.last_activity_at,
                    target_ref=(
                        None if descriptor.target_ref is None else str(descriptor.target_ref)
                    ),
                    identity_ref=(
                        None if descriptor.identity_ref is None else str(descriptor.identity_ref)
                    ),
                    access_context_ref=(
                        None
                        if descriptor.access_context_ref is None
                        else str(descriptor.access_context_ref)
                    ),
                    resource_refs_json=[str(ref) for ref in descriptor.resource_refs],
                    supported_operations_json=list(descriptor.supported_operations),
                    access_modes_json=[mode.value for mode in descriptor.access_modes],
                    lifecycle_metadata_json=deepcopy(descriptor.lifecycle_metadata),
                )
            )

    def get_session(self, session_ref: SessionRef) -> SessionRuntimeRecord | None:
        with self._database.transaction() as session:
            row = session.get(RuntimeSessionRow, str(session_ref))
            return None if row is None else _session_record(row)

    def list_sessions(self) -> tuple[SessionRuntimeRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(select(RuntimeSessionRow).order_by(RuntimeSessionRow.session_id))
            return tuple(_session_record(row) for row in rows)

    def list_sessions_for_resource(
        self, resource_ref: ResourceRef
    ) -> tuple[SessionRuntimeRecord, ...]:
        return tuple(
            record
            for record in self.list_sessions()
            if resource_ref in record.descriptor.resource_refs
        )

    def update_session_state(
        self,
        session_ref: SessionRef,
        state: SessionRuntimeState,
        occurred_at: datetime,
    ) -> None:
        with self._database.transaction() as session:
            row = session.get(RuntimeSessionRow, str(session_ref))
            if row is None:
                raise KeyError(f"unknown Session: {session_ref}")
            row.state = state.value
            row.updated_at = occurred_at
            row.last_activity_at = occurred_at

    def touch_session(self, session_ref: SessionRef, occurred_at: datetime) -> None:
        with self._database.transaction() as session:
            row = session.get(RuntimeSessionRow, str(session_ref))
            if row is None:
                raise KeyError(f"unknown Session: {session_ref}")
            row.updated_at = occurred_at
            row.last_activity_at = occurred_at

    def runtime_resource_count(self) -> int:
        with self._database.transaction() as session:
            return int(session.scalar(select(func.count()).select_from(RuntimeResourceRow)) or 0)

    def runtime_session_count(self) -> int:
        with self._database.transaction() as session:
            return int(session.scalar(select(func.count()).select_from(RuntimeSessionRow)) or 0)

    def recover_non_restorable_browser_state(self, recovered_at: datetime) -> tuple[int, int]:
        """Mark live browser metadata LOST; live Playwright objects cannot survive restart."""

        return self._recover_non_restorable_state(
            resource_types=("browser_process",),
            session_types=("browser",),
            recovered_at=recovered_at,
        )

    def recover_non_restorable_listener_state(self, recovered_at: datetime) -> tuple[int, int]:
        """Mark raw TCP listener and stream metadata LOST after process restart."""

        return self._recover_non_restorable_state(
            resource_types=("tcp_listener",),
            session_types=("tcp_stream",),
            recovered_at=recovered_at,
        )

    def _recover_non_restorable_state(
        self,
        *,
        resource_types: tuple[str, ...],
        session_types: tuple[str, ...],
        recovered_at: datetime,
    ) -> tuple[int, int]:
        resources_lost = 0
        sessions_lost = 0
        with self._database.transaction() as session:
            resources = session.scalars(
                select(RuntimeResourceRow).where(
                    RuntimeResourceRow.resource_type.in_(resource_types),
                    RuntimeResourceRow.state.in_(
                        [
                            ResourceRuntimeState.CREATING.value,
                            ResourceRuntimeState.READY.value,
                            ResourceRuntimeState.CLOSING.value,
                        ]
                    ),
                )
            )
            for resource_row in resources:
                resource_row.state = ResourceRuntimeState.LOST.value
                resource_row.updated_at = recovered_at
                resource_row.last_activity_at = recovered_at
                resources_lost += 1
            sessions = session.scalars(
                select(RuntimeSessionRow).where(
                    RuntimeSessionRow.session_type.in_(session_types),
                    RuntimeSessionRow.state.in_(
                        [
                            SessionRuntimeState.CREATING.value,
                            SessionRuntimeState.ACTIVE.value,
                            SessionRuntimeState.CLOSING.value,
                        ]
                    ),
                )
            )
            for session_row in sessions:
                session_row.state = SessionRuntimeState.LOST.value
                session_row.updated_at = recovered_at
                session_row.last_activity_at = recovered_at
                sessions_lost += 1
        return resources_lost, sessions_lost

    def add_artifact(self, record: SpoolArtifactRecord) -> None:
        descriptor = record.descriptor
        if descriptor.sha256 is None or descriptor.size_bytes is None:
            raise ValueError("spooled Artifacts require a content hash and size")
        with self._database.transaction() as session:
            session.add(
                ArtifactRow(
                    artifact_id=str(descriptor.artifact_id),
                    artifact_type=descriptor.artifact_type,
                    storage_ref=str(descriptor.storage_ref),
                    run_id=str(descriptor.created_by_run),
                    created_at=descriptor.created_at,
                    sha256=descriptor.sha256,
                    size_bytes=descriptor.size_bytes,
                    media_type=descriptor.media_type,
                    metadata_json=deepcopy(descriptor.metadata),
                    local_path=record.local_path,
                    sync_state=record.sync_state.value,
                    sync_attempt_count=record.sync_attempt_count,
                    last_sync_attempt_at=record.last_sync_attempt_at,
                    sync_error=record.sync_error,
                )
            )

    def get_artifact(self, artifact_ref: ArtifactRef) -> SpoolArtifactRecord | None:
        with self._database.transaction() as session:
            row = session.get(ArtifactRow, str(artifact_ref))
            return None if row is None else _artifact_record(row)

    def list_artifacts_for_run(self, run_ref: CapabilityRunRef) -> tuple[SpoolArtifactRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(ArtifactRow)
                .where(ArtifactRow.run_id == str(run_ref))
                .order_by(ArtifactRow.artifact_id)
            )
            return tuple(_artifact_record(row) for row in rows)

    def list_artifacts_for_sync(self) -> tuple[SpoolArtifactRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(ArtifactRow)
                .where(
                    ArtifactRow.sync_state.in_(
                        [
                            ArtifactSyncState.LOCAL_ONLY.value,
                            ArtifactSyncState.SYNC_PENDING.value,
                            ArtifactSyncState.SYNC_FAILED.value,
                        ]
                    )
                )
                .order_by(ArtifactRow.created_at, ArtifactRow.artifact_id)
            )
            return tuple(_artifact_record(row) for row in rows)

    def begin_artifact_sync(self, artifact_ref: ArtifactRef, attempted_at: datetime) -> None:
        with self._database.transaction() as session:
            row = session.get(ArtifactRow, str(artifact_ref))
            if row is None:
                raise KeyError(f"unknown local Artifact: {artifact_ref}")
            if ArtifactSyncState(row.sync_state) is ArtifactSyncState.SYNCED:
                return
            row.sync_state = ArtifactSyncState.SYNC_PENDING.value
            row.sync_attempt_count += 1
            row.last_sync_attempt_at = attempted_at
            row.sync_error = None

    def complete_artifact_sync(self, artifact_ref: ArtifactRef) -> None:
        with self._database.transaction() as session:
            row = session.get(ArtifactRow, str(artifact_ref))
            if row is None:
                raise KeyError(f"unknown local Artifact: {artifact_ref}")
            row.sync_state = ArtifactSyncState.SYNCED.value
            row.sync_error = None

    def fail_artifact_sync(self, artifact_ref: ArtifactRef, error: str) -> None:
        with self._database.transaction() as session:
            row = session.get(ArtifactRow, str(artifact_ref))
            if row is None:
                raise KeyError(f"unknown local Artifact: {artifact_ref}")
            row.sync_state = ArtifactSyncState.SYNC_FAILED.value
            row.sync_error = error

    def artifact_count(self) -> int:
        with self._database.transaction() as session:
            return int(session.scalar(select(func.count()).select_from(ArtifactRow)) or 0)

    def enqueue_event(self, event: Event) -> None:
        event_json = _json_object_adapter.validate_python(event.model_dump(mode="json"))
        with self._database.transaction() as session:
            existing = session.scalar(
                select(EventOutboxRow).where(EventOutboxRow.event_id == str(event.event_id))
            )
            if existing is not None:
                if existing.event_json != event_json:
                    raise ValueError(f"Event identity collision: {event.event_id}")
                return
            session.add(
                EventOutboxRow(
                    event_id=str(event.event_id),
                    event_json=event_json,
                    delivery_state=DeliveryState.PENDING.value,
                    created_at=event.timestamp,
                )
            )

    def pending_events(self) -> tuple[EventOutboxRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(EventOutboxRow)
                .where(EventOutboxRow.delivery_state == DeliveryState.PENDING.value)
                .order_by(EventOutboxRow.sequence)
            )
            return tuple(
                EventOutboxRecord(
                    sequence=row.sequence,
                    event=Event.model_validate(row.event_json),
                    delivery_state=DeliveryState(row.delivery_state),
                    created_at=row.created_at,
                )
                for row in rows
            )

    def mark_event_delivered(self, sequence: int) -> None:
        with self._database.transaction() as session:
            row = session.get(EventOutboxRow, sequence)
            if row is None:
                raise KeyError(f"unknown Event outbox sequence: {sequence}")
            row.delivery_state = DeliveryState.DELIVERED.value

    def acknowledge_event(self, event_ref: EventRef, correlation_id: CapabilityRunRef) -> None:
        with self._database.transaction() as session:
            row = session.scalar(
                select(EventOutboxRow).where(EventOutboxRow.event_id == str(event_ref))
            )
            if row is None:
                raise KeyError(f"unknown Event outbox identity: {event_ref}")
            event = Event.model_validate(row.event_json)
            if str(event.source_ref) != str(correlation_id):
                raise ValueError("Event acknowledgement correlation does not match")
            row.delivery_state = DeliveryState.DELIVERED.value

    def enqueue_result_and_finish_run(
        self,
        result: CapabilityResult,
        *,
        finished_at: datetime,
        error_code: str | None = None,
    ) -> None:
        result_json = _json_object_adapter.validate_python(result.model_dump(mode="json"))
        with self._database.transaction() as session:
            run = session.get(RunRow, str(result.run_ref))
            if run is None:
                raise KeyError(f"unknown local CapabilityRun: {result.run_ref}")
            existing = session.scalar(
                select(ResultOutboxRow).where(ResultOutboxRow.run_id == str(result.run_ref))
            )
            if existing is not None:
                if existing.result_json != result_json:
                    raise ValueError(f"Result identity collision: {result.run_ref}")
            else:
                session.add(
                    ResultOutboxRow(
                        run_id=str(result.run_ref),
                        result_json=result_json,
                        delivery_state=DeliveryState.PENDING.value,
                        created_at=finished_at,
                    )
                )
            run.status = result.execution_status.value
            run.finished_at = finished_at
            run.error_code = error_code

    def get_result(self, run_ref: CapabilityRunRef) -> CapabilityResult | None:
        with self._database.transaction() as session:
            row = session.scalar(
                select(ResultOutboxRow).where(ResultOutboxRow.run_id == str(run_ref))
            )
            return None if row is None else CapabilityResult.model_validate(row.result_json)

    def pending_results(self) -> tuple[ResultOutboxRecord, ...]:
        with self._database.transaction() as session:
            rows = session.scalars(
                select(ResultOutboxRow)
                .where(ResultOutboxRow.delivery_state == DeliveryState.PENDING.value)
                .order_by(ResultOutboxRow.sequence)
            )
            return tuple(
                ResultOutboxRecord(
                    sequence=row.sequence,
                    run_ref=CapabilityRunRef(row.run_id),
                    result_json=deepcopy(row.result_json),
                    delivery_state=DeliveryState(row.delivery_state),
                    created_at=row.created_at,
                )
                for row in rows
            )

    def mark_result_delivered(self, sequence: int) -> None:
        with self._database.transaction() as session:
            row = session.get(ResultOutboxRow, sequence)
            if row is None:
                raise KeyError(f"unknown Result outbox sequence: {sequence}")
            row.delivery_state = DeliveryState.DELIVERED.value

    def acknowledge_result(
        self, run_ref: CapabilityRunRef, correlation_id: CapabilityRunRef
    ) -> None:
        if run_ref != correlation_id:
            raise ValueError("Result acknowledgement correlation does not match")
        with self._database.transaction() as session:
            row = session.scalar(
                select(ResultOutboxRow).where(ResultOutboxRow.run_id == str(run_ref))
            )
            if row is None:
                raise KeyError(f"unknown Result outbox identity: {run_ref}")
            row.delivery_state = DeliveryState.DELIVERED.value

    def recover_interrupted(self, recovered_at: datetime) -> tuple[tuple[RunRecord, ...], int]:
        """Conservatively classify unprovable live state after restart."""

        recovered_runs: list[RunRecord] = []
        recovered_processes = 0
        with self._database.transaction() as session:
            runs = session.scalars(
                select(RunRow).where(
                    RunRow.status.in_(
                        [
                            CapabilityRunStatus.RUNNING.value,
                            CapabilityRunStatus.QUEUED.value,
                            CapabilityRunStatus.WAITING_INPUT.value,
                        ]
                    )
                )
            )
            for run in runs:
                run.status = CapabilityRunStatus.FAILED.value
                run.finished_at = recovered_at
                run.error_code = "INTERRUPTED_EXECUTION_STATE_UNKNOWN"
                recovered_runs.append(_run_record(run))
                interactions = session.scalars(
                    select(RuntimeInteractionRow).where(
                        RuntimeInteractionRow.run_id == run.run_id,
                        RuntimeInteractionRow.state == InteractionLifecycle.REQUESTED.value,
                    )
                )
                for interaction in interactions:
                    interaction.state = InteractionLifecycle.CANCELLED.value
                    interaction.cancelled_at = recovered_at
                    interaction.cancellation_reason = (
                        "Execution Node restarted; suspended capability state was not restorable"
                    )
            processes = session.scalars(
                select(ProcessRow).where(ProcessRow.state == ProcessState.RUNNING.value)
            )
            for process in processes:
                process.state = ProcessState.LOST.value
                process.finished_at = recovered_at
                recovered_processes += 1
        return tuple(recovered_runs), recovered_processes


def _run_record(row: RunRow) -> RunRecord:
    return RunRecord(
        run_ref=CapabilityRunRef(row.run_id),
        mission_ref=MissionRef(row.mission_id),
        capability_id=row.capability_id,
        operation=row.operation,
        status=CapabilityRunStatus(row.status),
        created_at=row.created_at,
        parent_run_ref=(None if row.parent_run_id is None else CapabilityRunRef(row.parent_run_id)),
        workflow_run_ref=(
            None if row.workflow_run_id is None else WorkflowRunRef(row.workflow_run_id)
        ),
        invocation_fingerprint=row.invocation_fingerprint,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_code=row.error_code,
    )


def _interaction_record(row: RuntimeInteractionRow) -> InteractionRuntimeRecord:
    return InteractionRuntimeRecord(
        request=InteractionRequest.model_validate(deepcopy(row.request_json)),
        state=InteractionLifecycle(row.state),
        response=(
            None
            if row.response_json is None
            else InteractionResponse.model_validate(deepcopy(row.response_json))
        ),
        cancelled_at=row.cancelled_at,
        cancellation_reason=row.cancellation_reason,
    )


def _process_record(row: ProcessRow) -> ProcessRecord:
    return ProcessRecord(
        process_id=row.process_id,
        run_ref=CapabilityRunRef(row.run_id),
        tool=row.tool,
        state=ProcessState(row.state),
        argument_count=row.argument_count,
        pid=row.pid,
        started_at=row.started_at,
        finished_at=row.finished_at,
        exit_code=row.exit_code,
    )


def _workspace_record(row: WorkspaceRow) -> WorkspaceRecord:
    return WorkspaceRecord(
        workspace_ref=WorkspaceRef(row.workspace_id),
        owner_ref=row.owner_ref,
        purpose=row.purpose,
        isolation=WorkspaceIsolation(row.isolation),
        local_path=row.local_path,
        state=WorkspaceState(row.state),
        created_at=row.created_at,
    )


def _artifact_record(row: ArtifactRow) -> SpoolArtifactRecord:
    descriptor = ArtifactDescriptor(
        artifact_id=ArtifactRef(row.artifact_id),
        artifact_type=row.artifact_type,
        storage_ref=StorageRef(row.storage_ref),
        created_by_run=CapabilityRunRef(row.run_id),
        created_at=row.created_at,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        media_type=row.media_type,
        metadata=deepcopy(row.metadata_json),
    )
    return SpoolArtifactRecord(
        descriptor=descriptor,
        local_path=row.local_path,
        sync_state=ArtifactSyncState(row.sync_state),
        sync_attempt_count=row.sync_attempt_count,
        last_sync_attempt_at=row.last_sync_attempt_at,
        sync_error=row.sync_error,
    )


def _resource_record(row: RuntimeResourceRow) -> ResourceRuntimeRecord:
    descriptor = ResourceDescriptor(
        resource_id=ResourceRef(row.resource_id),
        resource_type=row.resource_type,
        provider=row.provider,
        state=row.state,
        owner_ref=DomainRef(row.owner_ref),
        created_by_run=CapabilityRunRef(row.created_by_run),
        created_at=row.created_at,
        access_modes=tuple(AccessMode(mode) for mode in row.access_modes_json),
        expires_at=row.expires_at,
        lifecycle_metadata=deepcopy(row.lifecycle_metadata_json),
    )
    return ResourceRuntimeRecord(
        descriptor=descriptor,
        updated_at=row.updated_at,
        last_activity_at=row.last_activity_at,
    )


def _session_record(row: RuntimeSessionRow) -> SessionRuntimeRecord:
    descriptor = SessionDescriptor(
        session_id=SessionRef(row.session_id),
        session_type=row.session_type,
        state=row.state,
        provider=row.provider,
        owner_ref=DomainRef(row.owner_ref),
        created_by_run=CapabilityRunRef(row.created_by_run),
        created_at=row.created_at,
        target_ref=None if row.target_ref is None else DomainRef(row.target_ref),
        identity_ref=None if row.identity_ref is None else IdentityRef(row.identity_ref),
        access_context_ref=(
            None if row.access_context_ref is None else AccessContextRef(row.access_context_ref)
        ),
        resource_refs=tuple(ResourceRef(ref) for ref in row.resource_refs_json),
        supported_operations=tuple(row.supported_operations_json),
        access_modes=tuple(AccessMode(mode) for mode in row.access_modes_json),
        lifecycle_metadata=deepcopy(row.lifecycle_metadata_json),
    )
    return SessionRuntimeRecord(
        descriptor=descriptor,
        updated_at=row.updated_at,
        last_activity_at=row.last_activity_at,
    )
