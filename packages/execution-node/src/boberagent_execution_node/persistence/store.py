"""Explicit repository facade for node-owned runtime state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityResult,
    CapabilityRunRef,
    CapabilityRunStatus,
    Event,
    EventRef,
    JsonObject,
    MissionRef,
    StorageRef,
    WorkflowRunRef,
)
from boberagent_sdk import WorkspaceIsolation, WorkspaceRef
from pydantic import TypeAdapter
from sqlalchemy import func, select

from .database import RuntimeDatabase
from .models import (
    ArtifactSyncState,
    DeliveryState,
    EventOutboxRecord,
    ProcessRecord,
    ProcessState,
    ResultOutboxRecord,
    RunRecord,
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
                        [CapabilityRunStatus.RUNNING.value, CapabilityRunStatus.QUEUED.value]
                    )
                )
            )
            for run in runs:
                run.status = CapabilityRunStatus.FAILED.value
                run.finished_at = recovered_at
                run.error_code = "INTERRUPTED_EXECUTION_STATE_UNKNOWN"
                recovered_runs.append(_run_record(run))
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
    )
