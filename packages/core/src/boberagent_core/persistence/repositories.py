"""Explicit Core repositories and ORM-to-domain mapping."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    AssetRef,
    CapabilityRun,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
    Observation,
    ObservationRef,
    ServiceRef,
    StorageRef,
    WorkflowRunRef,
)
from boberagent_contracts.enums import CapabilityRunStatus
from boberagent_contracts.refs import DomainRef
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from boberagent_core.models import (
    ArtifactContentState,
    Asset,
    Goal,
    GoalRef,
    GoalStatus,
    MaterializationStatus,
    Mission,
    Service,
    StoredArtifact,
    StoredObservation,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepDefinition,
    WorkflowStepRun,
    WorkflowStepStatus,
    WorkflowStepSuccessPolicy,
)

from .orm import (
    ArtifactRow,
    AssetRow,
    CapabilityRunRow,
    GoalRow,
    MissionRow,
    ObservationRow,
    ServiceRow,
    WorkflowRunRow,
    WorkflowStepRunRow,
)

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class PersistenceIntegrityError(ValueError):
    """A Core write violated a schema identity or ownership constraint."""


class MissionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, mission: Mission) -> None:
        self._session.add(
            MissionRow(
                mission_id=str(mission.mission_ref),
                status=mission.status,
                created_at=mission.created_at,
                name=mission.name,
                metadata_json=deepcopy(mission.metadata),
            )
        )
        _flush_identity(self._session, mission.mission_ref)

    def get(self, mission_ref: MissionRef) -> Mission | None:
        row = self._session.get(MissionRow, str(mission_ref))
        return None if row is None else _mission_from_row(row)

    def list_all(self) -> tuple[Mission, ...]:
        rows = self._session.scalars(select(MissionRow).order_by(MissionRow.mission_id))
        return tuple(_mission_from_row(row) for row in rows)


class AssetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, asset: Asset) -> None:
        self._session.add(
            AssetRow(
                asset_id=str(asset.asset_ref),
                mission_id=str(asset.mission_ref),
                kind=asset.kind,
                primary_address=asset.primary_address,
                created_at=asset.created_at,
                metadata_json=deepcopy(asset.metadata),
            )
        )
        _flush_identity(self._session, asset.asset_ref)

    def get(self, asset_ref: AssetRef) -> Asset | None:
        row = self._session.get(AssetRow, str(asset_ref))
        return None if row is None else _asset_from_row(row)

    def list_for_mission(self, mission_ref: MissionRef) -> tuple[Asset, ...]:
        rows = self._session.scalars(
            select(AssetRow)
            .where(AssetRow.mission_id == str(mission_ref))
            .order_by(AssetRow.asset_id)
        )
        return tuple(_asset_from_row(row) for row in rows)


class CapabilityRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: CapabilityRun) -> None:
        self._session.add(
            CapabilityRunRow(
                run_id=str(run.run_id),
                mission_id=str(run.mission_ref),
                capability_id=run.capability_id,
                operation=run.operation,
                status=run.status.value,
                created_at=run.created_at,
                started_at=run.started_at,
                finished_at=run.finished_at,
                parent_run_id=None if run.parent_run_ref is None else str(run.parent_run_ref),
                workflow_run_id=(
                    None if run.workflow_run_ref is None else str(run.workflow_run_ref)
                ),
            )
        )
        _flush_identity(self._session, run.run_id)

    def get(self, run_ref: CapabilityRunRef) -> CapabilityRun | None:
        row = self._session.get(CapabilityRunRow, str(run_ref))
        if row is None:
            return None
        return CapabilityRun(
            run_id=CapabilityRunRef(row.run_id),
            mission_ref=MissionRef(row.mission_id),
            capability_id=row.capability_id,
            operation=row.operation,
            status=CapabilityRunStatus(row.status),
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            parent_run_ref=(
                None if row.parent_run_id is None else CapabilityRunRef(row.parent_run_id)
            ),
            workflow_run_ref=(
                None if row.workflow_run_id is None else WorkflowRunRef(row.workflow_run_id)
            ),
        )

    def reconcile_terminal(
        self,
        run_ref: CapabilityRunRef,
        status: CapabilityRunStatus,
        *,
        finished_at: datetime,
    ) -> CapabilityRun:
        if not status.is_terminal:
            raise ValueError("CapabilityResult status must be terminal")
        row = self._session.get(CapabilityRunRow, str(run_ref))
        if row is None:
            raise KeyError(f"unknown CapabilityRun: {run_ref}")
        current = CapabilityRunStatus(row.status)
        if current.is_terminal and current is not status:
            raise PersistenceIntegrityError(
                f"CapabilityRun terminal status conflict: {run_ref} is {current.value}, "
                f"Result reports {status.value}"
            )
        row.status = status.value
        if row.finished_at is None:
            row.finished_at = finished_at
        self._session.flush()
        reconciled = self.get(run_ref)
        assert reconciled is not None
        return reconciled


class ArtifactRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, artifact: ArtifactDescriptor) -> None:
        self._session.add(
            ArtifactRow(
                artifact_id=str(artifact.artifact_id),
                artifact_type=artifact.artifact_type,
                storage_ref=str(artifact.storage_ref),
                run_id=str(artifact.created_by_run),
                created_at=artifact.created_at,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                media_type=artifact.media_type,
                metadata_json=deepcopy(artifact.metadata),
                content_state=ArtifactContentState.METADATA_ONLY.value,
                received_bytes=0,
            )
        )
        _flush_identity(self._session, artifact.artifact_id)

    def get(self, artifact_ref: ArtifactRef) -> ArtifactDescriptor | None:
        record = self.get_record(artifact_ref)
        return None if record is None else record.descriptor

    def get_record(self, artifact_ref: ArtifactRef) -> StoredArtifact | None:
        row = self._session.get(ArtifactRow, str(artifact_ref))
        return None if row is None else _stored_artifact_from_row(row)

    def reconcile(self, artifact: ArtifactDescriptor) -> StoredArtifact:
        """Insert metadata or merge compatible optional fields without changing content state."""

        row = self._session.get(ArtifactRow, str(artifact.artifact_id))
        if row is None:
            self.add(artifact)
            created = self.get_record(artifact.artifact_id)
            assert created is not None
            return created
        _validate_artifact_identity(row, artifact)
        if row.sha256 is None:
            row.sha256 = artifact.sha256
        if row.size_bytes is None:
            row.size_bytes = artifact.size_bytes
        if row.media_type is None:
            row.media_type = artifact.media_type
        merged_metadata = deepcopy(row.metadata_json)
        for key, value in artifact.metadata.items():
            if key in merged_metadata and merged_metadata[key] != value:
                raise PersistenceIntegrityError(
                    f"ArtifactRef has conflicting metadata field {key!r}: {artifact.artifact_id}"
                )
            merged_metadata[key] = deepcopy(value)
        row.metadata_json = merged_metadata
        self._session.flush()
        return _stored_artifact_from_row(row)

    def prepare_transfer(
        self,
        artifact: ArtifactDescriptor,
        *,
        source_node_id: str,
        transfer_id: str,
    ) -> StoredArtifact:
        row = self._session.get(ArtifactRow, str(artifact.artifact_id))
        if row is None:
            row = ArtifactRow(
                artifact_id=str(artifact.artifact_id),
                artifact_type=artifact.artifact_type,
                storage_ref=str(artifact.storage_ref),
                run_id=str(artifact.created_by_run),
                created_at=artifact.created_at,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                media_type=artifact.media_type,
                metadata_json=deepcopy(artifact.metadata),
                content_state=ArtifactContentState.RECEIVING.value,
                source_node_id=source_node_id,
                transfer_id=transfer_id,
                received_bytes=0,
            )
            self._session.add(row)
            _flush_identity(self._session, artifact.artifact_id)
            return _stored_artifact_from_row(row)

        if _artifact_descriptor_from_row(row) != artifact:
            raise PersistenceIntegrityError(
                f"ArtifactRef has incompatible canonical metadata: {artifact.artifact_id}"
            )
        state = ArtifactContentState(row.content_state)
        if state is ArtifactContentState.AVAILABLE:
            return _stored_artifact_from_row(row)
        if state is ArtifactContentState.RECEIVING and (
            row.source_node_id != source_node_id or row.transfer_id != transfer_id
        ):
            raise PersistenceIntegrityError(
                f"ArtifactRef already has a different active transfer: {artifact.artifact_id}"
            )
        if state in {ArtifactContentState.METADATA_ONLY, ArtifactContentState.FAILED}:
            row.received_bytes = 0
        row.content_state = ArtifactContentState.RECEIVING.value
        row.source_node_id = source_node_id
        row.transfer_id = transfer_id
        row.sync_error = None
        self._session.flush()
        return _stored_artifact_from_row(row)

    def set_transfer_progress(self, artifact_ref: ArtifactRef, received_bytes: int) -> None:
        row = self._required_transfer_row(artifact_ref)
        row.received_bytes = received_bytes
        self._session.flush()

    def complete_transfer(self, artifact_ref: ArtifactRef, content_key: str) -> StoredArtifact:
        row = self._required_transfer_row(artifact_ref)
        if row.size_bytes is None or row.received_bytes != row.size_bytes:
            raise PersistenceIntegrityError("Artifact transfer cannot complete before all bytes")
        row.content_state = ArtifactContentState.AVAILABLE.value
        row.content_key = content_key
        row.sync_error = None
        self._session.flush()
        return _stored_artifact_from_row(row)

    def fail_transfer(self, artifact_ref: ArtifactRef, error: str) -> None:
        row = self._session.get(ArtifactRow, str(artifact_ref))
        if row is None:
            raise KeyError(f"unknown Artifact: {artifact_ref}")
        row.content_state = ArtifactContentState.FAILED.value
        row.received_bytes = 0
        row.sync_error = error
        self._session.flush()

    def content_key(self, artifact_ref: ArtifactRef) -> str | None:
        row = self._session.get(ArtifactRow, str(artifact_ref))
        return None if row is None else row.content_key

    def transfer_identity(self, artifact_ref: ArtifactRef) -> tuple[str, str] | None:
        row = self._session.get(ArtifactRow, str(artifact_ref))
        if row is None or row.source_node_id is None or row.transfer_id is None:
            return None
        return row.source_node_id, row.transfer_id

    def _required_transfer_row(self, artifact_ref: ArtifactRef) -> ArtifactRow:
        row = self._session.get(ArtifactRow, str(artifact_ref))
        if row is None:
            raise KeyError(f"unknown Artifact: {artifact_ref}")
        if ArtifactContentState(row.content_state) is not ArtifactContentState.RECEIVING:
            raise PersistenceIntegrityError(f"Artifact is not receiving content: {artifact_ref}")
        return row


class ObservationRepository:
    """Append observations; only their separate processing metadata is mutable."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, observation: Observation) -> None:
        self._session.add(
            ObservationRow(
                observation_id=str(observation.observation_id),
                observation_type=observation.type,
                subject_ref=(
                    None if observation.subject_ref is None else str(observation.subject_ref)
                ),
                value_json=deepcopy(observation.value),
                confidence=observation.confidence,
                observed_at=observation.observed_at,
                run_id=str(observation.run_ref),
                evidence_refs_json=[str(ref) for ref in observation.evidence_refs],
                materialization_status=MaterializationStatus.PENDING.value,
                materialization_error=None,
            )
        )
        _flush_identity(self._session, observation.observation_id)

    def reconcile(self, observation: Observation) -> StoredObservation:
        """Append once, accepting exact immutable replays and rejecting identity conflicts."""

        existing = self.get(observation.observation_id)
        if existing is None:
            self.append(observation)
            created = self.get(observation.observation_id)
            assert created is not None
            return created
        if existing.observation != observation:
            raise PersistenceIntegrityError(
                f"ObservationRef has conflicting immutable content: {observation.observation_id}"
            )
        return existing

    def get(self, observation_ref: ObservationRef) -> StoredObservation | None:
        row = self._session.get(ObservationRow, str(observation_ref))
        return None if row is None else _observation_from_row(row)

    def list_pending(self, *, limit: int | None = None) -> tuple[StoredObservation, ...]:
        statement = (
            select(ObservationRow)
            .where(ObservationRow.materialization_status == MaterializationStatus.PENDING.value)
            .order_by(ObservationRow.observed_at, ObservationRow.observation_id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return tuple(_observation_from_row(row) for row in self._session.scalars(statement))

    def set_materialization(
        self,
        observation_ref: ObservationRef,
        status: MaterializationStatus,
        *,
        error: str | None = None,
    ) -> None:
        row = self._session.get(ObservationRow, str(observation_ref))
        if row is None:
            raise KeyError(f"unknown Observation: {observation_ref}")
        row.materialization_status = status.value
        row.materialization_error = error
        self._session.flush()


class ServiceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_endpoint(self, asset_ref: AssetRef, transport: str, port: int) -> Service | None:
        row = self._session.scalar(
            select(ServiceRow).where(
                ServiceRow.asset_id == str(asset_ref),
                ServiceRow.transport == transport,
                ServiceRow.port == port,
            )
        )
        return None if row is None else _service_from_row(row)

    def list_for_asset(self, asset_ref: AssetRef) -> tuple[Service, ...]:
        rows = self._session.scalars(
            select(ServiceRow)
            .where(ServiceRow.asset_id == str(asset_ref))
            .order_by(ServiceRow.transport, ServiceRow.port)
        )
        return tuple(_service_from_row(row) for row in rows)

    def upsert_current(self, service: Service) -> Service:
        row = self._session.get(ServiceRow, str(service.service_ref))
        if row is None:
            row = ServiceRow(
                service_id=str(service.service_ref),
                asset_id=str(service.asset_ref),
                transport=service.transport,
                port=service.port,
                state=service.state,
                service=service.service,
                product=service.product,
                version=service.version,
                first_observed_at=service.first_observed_at,
                last_observed_at=service.last_observed_at,
                current_observation_id=str(service.current_observation_ref),
                provenance_refs_json=[str(ref) for ref in service.provenance_refs],
            )
            self._session.add(row)
        else:
            row.state = service.state
            row.service = service.service
            row.product = service.product
            row.version = service.version
            row.first_observed_at = service.first_observed_at
            row.last_observed_at = service.last_observed_at
            row.current_observation_id = str(service.current_observation_ref)
            row.provenance_refs_json = [str(ref) for ref in service.provenance_refs]
        self._session.flush()
        return _service_from_row(row)


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workflow: WorkflowRun) -> None:
        definition_json = (
            None
            if workflow.definition is None
            else _json_object_adapter.validate_python(workflow.definition.model_dump(mode="json"))
        )
        self._session.add(
            WorkflowRunRow(
                workflow_run_id=str(workflow.workflow_run_ref),
                mission_id=str(workflow.mission_ref),
                procedure_ref=workflow.procedure_ref,
                status=workflow.status.value,
                created_at=workflow.created_at,
                updated_at=workflow.updated_at,
                definition_json=deepcopy(definition_json),
                failure_reason=workflow.failure_reason,
            )
        )
        _flush_identity(self._session, workflow.workflow_run_ref)

    def get(self, workflow_ref: WorkflowRunRef) -> WorkflowRun | None:
        row = self._session.get(WorkflowRunRow, str(workflow_ref))
        if row is None:
            return None
        return WorkflowRun(
            workflow_run_ref=WorkflowRunRef(row.workflow_run_id),
            mission_ref=MissionRef(row.mission_id),
            procedure_ref=row.procedure_ref,
            status=WorkflowStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
            definition=(
                None
                if row.definition_json is None
                else WorkflowDefinition.model_validate(deepcopy(row.definition_json))
            ),
            failure_reason=row.failure_reason,
        )

    def set_status(
        self,
        workflow_ref: WorkflowRunRef,
        status: WorkflowStatus,
        *,
        updated_at: datetime,
        failure_reason: str | None = None,
    ) -> WorkflowRun:
        row = self._session.get(WorkflowRunRow, str(workflow_ref))
        if row is None:
            raise KeyError(f"unknown WorkflowRun: {workflow_ref}")
        current = WorkflowStatus(row.status)
        if current.is_terminal and current is not status:
            raise PersistenceIntegrityError(
                f"terminal WorkflowRun cannot transition from {current.value} to {status.value}"
            )
        row.status = status.value
        row.updated_at = updated_at
        row.failure_reason = failure_reason
        self._session.flush()
        updated = self.get(workflow_ref)
        assert updated is not None
        return updated


class WorkflowStepRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, step: WorkflowStepRun) -> None:
        self._session.add(
            WorkflowStepRunRow(
                workflow_run_id=str(step.workflow_run_ref),
                step_id=step.step_id,
                position=step.position,
                capability_id=step.definition.capability_id,
                operation=step.definition.operation,
                inputs_json=deepcopy(step.definition.inputs),
                success_policy=step.definition.success_policy.value,
                status=step.status.value,
                capability_run_id=(
                    None if step.capability_run_ref is None else str(step.capability_run_ref)
                ),
                created_at=step.created_at,
                updated_at=step.updated_at,
                completed_at=step.completed_at,
                failure_reason=step.failure_reason,
            )
        )
        self._session.flush()

    def get(self, workflow_ref: WorkflowRunRef, step_id: str) -> WorkflowStepRun | None:
        row = self._session.get(WorkflowStepRunRow, (str(workflow_ref), step_id))
        return None if row is None else _workflow_step_from_row(row)

    def list_for_workflow(self, workflow_ref: WorkflowRunRef) -> tuple[WorkflowStepRun, ...]:
        rows = self._session.scalars(
            select(WorkflowStepRunRow)
            .where(WorkflowStepRunRow.workflow_run_id == str(workflow_ref))
            .order_by(WorkflowStepRunRow.position)
        )
        return tuple(_workflow_step_from_row(row) for row in rows)

    def prepare(
        self,
        workflow_ref: WorkflowRunRef,
        step_id: str,
        run_ref: CapabilityRunRef,
        *,
        updated_at: datetime,
    ) -> WorkflowStepRun:
        row = self._required(workflow_ref, step_id)
        status = WorkflowStepStatus(row.status)
        if status is WorkflowStepStatus.PENDING:
            row.status = WorkflowStepStatus.PREPARED.value
            row.capability_run_id = str(run_ref)
            row.updated_at = updated_at
        elif status is not WorkflowStepStatus.PREPARED or row.capability_run_id != str(run_ref):
            raise PersistenceIntegrityError(
                f"Workflow step cannot be prepared from {status.value}: {workflow_ref}/{step_id}"
            )
        self._session.flush()
        return _workflow_step_from_row(row)

    def mark_active(
        self,
        workflow_ref: WorkflowRunRef,
        step_id: str,
        *,
        updated_at: datetime,
    ) -> WorkflowStepRun:
        row = self._required(workflow_ref, step_id)
        status = WorkflowStepStatus(row.status)
        if status is WorkflowStepStatus.PREPARED:
            row.status = WorkflowStepStatus.ACTIVE.value
            row.updated_at = updated_at
        elif status is not WorkflowStepStatus.ACTIVE:
            raise PersistenceIntegrityError(
                f"Workflow step cannot become active from {status.value}: {workflow_ref}/{step_id}"
            )
        self._session.flush()
        return _workflow_step_from_row(row)

    def finish(
        self,
        workflow_ref: WorkflowRunRef,
        step_id: str,
        status: WorkflowStepStatus,
        *,
        updated_at: datetime,
        failure_reason: str | None = None,
    ) -> WorkflowStepRun:
        if status not in {
            WorkflowStepStatus.COMPLETED,
            WorkflowStepStatus.FAILED,
            WorkflowStepStatus.CANCELLED,
        }:
            raise ValueError("Workflow step finish status must be terminal")
        row = self._required(workflow_ref, step_id)
        current = WorkflowStepStatus(row.status)
        if current.is_terminal:
            if current is not status:
                raise PersistenceIntegrityError(
                    f"terminal Workflow step cannot transition from {current.value} "
                    f"to {status.value}"
                )
            return _workflow_step_from_row(row)
        row.status = status.value
        row.updated_at = updated_at
        row.completed_at = updated_at
        row.failure_reason = failure_reason
        self._session.flush()
        return _workflow_step_from_row(row)

    def cancel_nonterminal(
        self, workflow_ref: WorkflowRunRef, *, updated_at: datetime
    ) -> tuple[WorkflowStepRun, ...]:
        rows = tuple(
            self._session.scalars(
                select(WorkflowStepRunRow).where(
                    WorkflowStepRunRow.workflow_run_id == str(workflow_ref)
                )
            )
        )
        for row in rows:
            if not WorkflowStepStatus(row.status).is_terminal:
                row.status = WorkflowStepStatus.CANCELLED.value
                row.updated_at = updated_at
                row.completed_at = updated_at
                row.failure_reason = "Workflow was cancelled"
        self._session.flush()
        return tuple(
            _workflow_step_from_row(row) for row in sorted(rows, key=lambda item: item.position)
        )

    def _required(self, workflow_ref: WorkflowRunRef, step_id: str) -> WorkflowStepRunRow:
        row = self._session.get(WorkflowStepRunRow, (str(workflow_ref), step_id))
        if row is None:
            raise KeyError(f"unknown Workflow step: {workflow_ref}/{step_id}")
        return row


class GoalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, goal: Goal) -> None:
        self._session.add(
            GoalRow(
                goal_id=str(goal.goal_ref),
                mission_id=str(goal.mission_ref),
                workflow_run_id=(
                    None if goal.workflow_run_ref is None else str(goal.workflow_run_ref)
                ),
                goal_type=goal.goal_type,
                parameters_json=deepcopy(goal.parameters),
                status=goal.status.value,
                created_at=goal.created_at,
                updated_at=goal.updated_at,
            )
        )
        _flush_identity(self._session, goal.goal_ref)

    def get(self, goal_ref: GoalRef) -> Goal | None:
        row = self._session.get(GoalRow, str(goal_ref))
        return None if row is None else _goal_from_row(row)

    def list_for_mission(self, mission_ref: MissionRef) -> tuple[Goal, ...]:
        rows = self._session.scalars(
            select(GoalRow).where(GoalRow.mission_id == str(mission_ref)).order_by(GoalRow.goal_id)
        )
        return tuple(_goal_from_row(row) for row in rows)


class CoreUnitOfWork:
    """Repository collection sharing one private SQLAlchemy transaction."""

    def __init__(self, session: Session) -> None:
        from boberagent_core.capabilities.repository import (
            CapabilityProviderRepository,
            RoutingDecisionRepository,
        )
        from boberagent_core.results.repository import ResultIngestionRepository
        from boberagent_core.transport.repository import TransportInboxRepository

        self.missions = MissionRepository(session)
        self.assets = AssetRepository(session)
        self.runs = CapabilityRunRepository(session)
        self.artifacts = ArtifactRepository(session)
        self.observations = ObservationRepository(session)
        self.services = ServiceRepository(session)
        self.workflows = WorkflowRepository(session)
        self.workflow_steps = WorkflowStepRepository(session)
        self.goals = GoalRepository(session)
        self.transport_inbox = TransportInboxRepository(session)
        self.capability_providers = CapabilityProviderRepository(session)
        self.routing_decisions = RoutingDecisionRepository(session)
        self.result_ingestions = ResultIngestionRepository(session)


def _flush_identity(session: Session, logical_ref: DomainRef) -> None:
    try:
        session.flush()
    except IntegrityError as error:
        raise PersistenceIntegrityError(
            f"could not persist logical identity {logical_ref}: integrity constraint failed"
        ) from error


def _mission_from_row(row: MissionRow) -> Mission:
    return Mission(
        mission_ref=MissionRef(row.mission_id),
        status=row.status,
        created_at=row.created_at,
        name=row.name,
        metadata=deepcopy(row.metadata_json),
    )


def _artifact_descriptor_from_row(row: ArtifactRow) -> ArtifactDescriptor:
    return ArtifactDescriptor(
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


def _validate_artifact_identity(row: ArtifactRow, incoming: ArtifactDescriptor) -> None:
    conflicts = (
        row.artifact_type != incoming.artifact_type
        or row.storage_ref != str(incoming.storage_ref)
        or row.run_id != str(incoming.created_by_run)
        or row.created_at != incoming.created_at
        or (
            row.sha256 is not None and incoming.sha256 is not None and row.sha256 != incoming.sha256
        )
        or (
            row.size_bytes is not None
            and incoming.size_bytes is not None
            and row.size_bytes != incoming.size_bytes
        )
        or (
            row.media_type is not None
            and incoming.media_type is not None
            and row.media_type != incoming.media_type
        )
    )
    if conflicts:
        raise PersistenceIntegrityError(
            f"ArtifactRef has incompatible canonical metadata: {incoming.artifact_id}"
        )


def _stored_artifact_from_row(row: ArtifactRow) -> StoredArtifact:
    return StoredArtifact(
        descriptor=_artifact_descriptor_from_row(row),
        content_state=ArtifactContentState(row.content_state),
        received_bytes=row.received_bytes,
        sync_error=row.sync_error,
    )


def _asset_from_row(row: AssetRow) -> Asset:
    return Asset(
        asset_ref=AssetRef(row.asset_id),
        mission_ref=MissionRef(row.mission_id),
        kind=row.kind,
        primary_address=row.primary_address,
        created_at=row.created_at,
        metadata=deepcopy(row.metadata_json),
    )


def _observation_from_row(row: ObservationRow) -> StoredObservation:
    subject = None if row.subject_ref is None else DomainRef(row.subject_ref)
    return StoredObservation(
        observation=Observation(
            observation_id=ObservationRef(row.observation_id),
            type=row.observation_type,
            subject_ref=subject,
            value=deepcopy(row.value_json),
            confidence=row.confidence,
            observed_at=row.observed_at,
            run_ref=CapabilityRunRef(row.run_id),
            evidence_refs=tuple(ArtifactRef(ref) for ref in row.evidence_refs_json),
        ),
        materialization_status=MaterializationStatus(row.materialization_status),
        materialization_error=row.materialization_error,
    )


def _service_from_row(row: ServiceRow) -> Service:
    return Service(
        service_ref=ServiceRef(row.service_id),
        asset_ref=AssetRef(row.asset_id),
        transport=row.transport,
        port=row.port,
        state=row.state,
        service=row.service,
        product=row.product,
        version=row.version,
        first_observed_at=row.first_observed_at,
        last_observed_at=row.last_observed_at,
        current_observation_ref=ObservationRef(row.current_observation_id),
        provenance_refs=tuple(ObservationRef(ref) for ref in row.provenance_refs_json),
    )


def _goal_from_row(row: GoalRow) -> Goal:
    return Goal(
        goal_ref=GoalRef(row.goal_id),
        mission_ref=MissionRef(row.mission_id),
        workflow_run_ref=(
            None if row.workflow_run_id is None else WorkflowRunRef(row.workflow_run_id)
        ),
        goal_type=row.goal_type,
        parameters=deepcopy(row.parameters_json),
        status=GoalStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _workflow_step_from_row(row: WorkflowStepRunRow) -> WorkflowStepRun:
    return WorkflowStepRun(
        workflow_run_ref=WorkflowRunRef(row.workflow_run_id),
        step_id=row.step_id,
        position=row.position,
        definition=WorkflowStepDefinition(
            step_id=row.step_id,
            capability_id=row.capability_id,
            operation=row.operation,
            inputs=deepcopy(row.inputs_json),
            success_policy=WorkflowStepSuccessPolicy(row.success_policy),
        ),
        status=WorkflowStepStatus(row.status),
        capability_run_ref=(
            None if row.capability_run_id is None else CapabilityRunRef(row.capability_run_id)
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        failure_reason=row.failure_reason,
    )
