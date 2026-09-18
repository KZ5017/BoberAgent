"""Explicitly pumped, durable, deterministic sequential Workflow orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4, uuid5

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    WorkflowRunRef,
)
from boberagent_transport import (
    AssetProjection,
    InvocationDelivery,
    MissionProjection,
    TransportError,
)

from boberagent_core.capabilities import CapabilityRouter, CapabilityRoutingError
from boberagent_core.clock import utc_now
from boberagent_core.models import (
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepRun,
    WorkflowStepStatus,
)
from boberagent_core.persistence import CoreDatabase
from boberagent_core.results import ResultIngestionStatus

from .errors import WorkflowDefinitionConflict, WorkflowNotFound, WorkflowStateError

_STEP_RUN_NAMESPACE = UUID("824c14c7-e3b2-55e0-bbac-9b78735c51a0")


class WorkflowService:
    """Drive one durable transition at a time without a scheduler or transport knowledge."""

    def __init__(
        self,
        database: CoreDatabase,
        router: CapabilityRouter | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._router = router
        self._clock = clock

    def create_run(
        self,
        definition: WorkflowDefinition,
        mission_ref: MissionRef,
        *,
        workflow_run_ref: WorkflowRunRef | None = None,
    ) -> WorkflowExecution:
        """Persist immutable intent and pending Step Runs without dispatching work."""

        run_ref = workflow_run_ref or WorkflowRunRef(f"workflow:{uuid4()}")
        now = self._now()
        with self._database.unit_of_work() as work:
            existing = work.workflows.get(run_ref)
            if existing is not None:
                if existing.mission_ref != mission_ref or existing.definition != definition:
                    raise WorkflowDefinitionConflict(
                        f"WorkflowRunRef already identifies different intent: {run_ref}"
                    )
                steps = work.workflow_steps.list_for_workflow(run_ref)
                return WorkflowExecution(run=existing, steps=steps)
            if work.missions.get(mission_ref) is None:
                raise KeyError(f"unknown Mission: {mission_ref}")
            workflow = WorkflowRun(
                workflow_run_ref=run_ref,
                mission_ref=mission_ref,
                procedure_ref=definition.procedure_ref,
                status=WorkflowStatus.CREATED,
                created_at=now,
                updated_at=now,
                definition=definition,
            )
            work.workflows.add(workflow)
            for position, step_definition in enumerate(definition.steps):
                work.workflow_steps.add(
                    WorkflowStepRun(
                        workflow_run_ref=run_ref,
                        step_id=step_definition.step_id,
                        position=position,
                        definition=step_definition,
                        status=WorkflowStepStatus.PENDING,
                        created_at=now,
                        updated_at=now,
                    )
                )
            steps = work.workflow_steps.list_for_workflow(run_ref)
        return WorkflowExecution(run=workflow, steps=steps)

    async def start(
        self,
        definition: WorkflowDefinition,
        mission_ref: MissionRef,
        *,
        workflow_run_ref: WorkflowRunRef | None = None,
    ) -> WorkflowExecution:
        self._require_router()
        created = self.create_run(
            definition,
            mission_ref,
            workflow_run_ref=workflow_run_ref,
        )
        return await self.advance(created.run.workflow_run_ref)

    async def advance(self, workflow_ref: WorkflowRunRef) -> WorkflowExecution:
        """Reconcile terminal Results and dispatch at most one new Capability step."""

        while True:
            execution = self._required_execution(workflow_ref)
            if execution.run.status.is_terminal:
                return execution
            if execution.run.definition is None:
                raise WorkflowStateError(
                    f"Workflow predates M11 and has no executable definition: {workflow_ref}"
                )

            current = next(
                (
                    step
                    for step in execution.steps
                    if step.status is not WorkflowStepStatus.COMPLETED
                ),
                None,
            )
            if current is None:
                return self._complete_workflow(workflow_ref)
            if current.status in {
                WorkflowStepStatus.FAILED,
                WorkflowStepStatus.CANCELLED,
            }:
                return self._fail_from_terminal_step(execution, current)
            if current.status is WorkflowStepStatus.PENDING:
                self._require_router()
                current = self._prepare_step(execution.run, current)
            if current.status is WorkflowStepStatus.PREPARED:
                self._require_router()
                return await self._dispatch_step(execution.run, current)
            if current.status is WorkflowStepStatus.ACTIVE:
                reconciled = self._reconcile_active_step(execution.run, current)
                if reconciled is None:
                    return self._required_execution(workflow_ref)
                if reconciled.status is WorkflowStepStatus.COMPLETED:
                    continue
                return self._required_execution(workflow_ref)
            raise WorkflowStateError(
                f"unsupported Workflow step state: {workflow_ref}/{current.step_id} "
                f"is {current.status.value}"
            )

    async def resume(self, workflow_ref: WorkflowRunRef) -> WorkflowExecution:
        """Alias that makes restart reconciliation explicit to callers."""

        return await self.advance(workflow_ref)

    def inspect(self, workflow_ref: WorkflowRunRef) -> WorkflowExecution | None:
        with self._database.unit_of_work() as work:
            run = work.workflows.get(workflow_ref)
            if run is None:
                return None
            return WorkflowExecution(
                run=run,
                steps=work.workflow_steps.list_for_workflow(workflow_ref),
            )

    def cancel(self, workflow_ref: WorkflowRunRef) -> WorkflowExecution:
        """Stop future orchestration; M11 does not add remote Capability cancellation."""

        now = self._now()
        with self._database.unit_of_work() as work:
            run = work.workflows.get(workflow_ref)
            if run is None:
                raise WorkflowNotFound(f"unknown WorkflowRun: {workflow_ref}")
            if not run.status.is_terminal:
                work.workflow_steps.cancel_nonterminal(workflow_ref, updated_at=now)
                work.workflows.set_status(
                    workflow_ref,
                    WorkflowStatus.CANCELLED,
                    updated_at=now,
                    failure_reason="Workflow was cancelled",
                )
        return self._required_execution(workflow_ref)

    def _prepare_step(self, workflow: WorkflowRun, step: WorkflowStepRun) -> WorkflowStepRun:
        run_ref = capability_run_ref_for_step(workflow.workflow_run_ref, step.step_id)
        now = self._now()
        with self._database.unit_of_work() as work:
            persisted = work.workflow_steps.get(workflow.workflow_run_ref, step.step_id)
            if persisted is None:
                raise WorkflowStateError(f"missing persisted Workflow step: {step.step_id}")
            if persisted.status is WorkflowStepStatus.PENDING:
                existing_run = work.runs.get(run_ref)
                if existing_run is None:
                    work.runs.add(
                        CapabilityRun(
                            run_id=run_ref,
                            capability_id=persisted.definition.capability_id,
                            operation=persisted.definition.operation,
                            mission_ref=workflow.mission_ref,
                            status=CapabilityRunStatus.CREATED,
                            created_at=now,
                            workflow_run_ref=workflow.workflow_run_ref,
                        )
                    )
                work.workflow_steps.prepare(
                    workflow.workflow_run_ref,
                    persisted.step_id,
                    run_ref,
                    updated_at=now,
                )
                work.workflows.set_status(
                    workflow.workflow_run_ref,
                    WorkflowStatus.RUNNING,
                    updated_at=now,
                )
            prepared = work.workflow_steps.get(workflow.workflow_run_ref, step.step_id)
            assert prepared is not None
            return prepared

    async def _dispatch_step(
        self, workflow: WorkflowRun, step: WorkflowStepRun
    ) -> WorkflowExecution:
        if step.capability_run_ref is None:
            raise WorkflowStateError(f"prepared step has no CapabilityRunRef: {step.step_id}")
        invocation = CapabilityInvocation(
            run_id=step.capability_run_ref,
            capability_id=step.definition.capability_id,
            operation=step.definition.operation,
            mission_ref=workflow.mission_ref,
            inputs=step.definition.inputs,
            workflow_run_ref=workflow.workflow_run_ref,
        )
        delivery = self._build_delivery(invocation)
        router = self._require_router()
        try:
            provider = router.selected_provider_for_run(invocation.run_id)
            if provider is None:
                provider = router.select_provider(
                    capability_id=invocation.capability_id,
                    operation=invocation.operation,
                )
            await router.dispatch(
                invocation=invocation,
                delivery=delivery,
                provider=provider,
            )
        except (CapabilityRoutingError, TransportError) as error:
            return self._mark_failed(
                workflow.workflow_run_ref,
                step.step_id,
                f"{type(error).__name__}: {error}",
            )

        now = self._now()
        with self._database.unit_of_work() as work:
            work.workflow_steps.mark_active(
                workflow.workflow_run_ref,
                step.step_id,
                updated_at=now,
            )
            work.workflows.set_status(
                workflow.workflow_run_ref,
                WorkflowStatus.RUNNING,
                updated_at=now,
            )
        return self._required_execution(workflow.workflow_run_ref)

    def _build_delivery(self, invocation: CapabilityInvocation) -> InvocationDelivery:
        with self._database.unit_of_work() as work:
            mission = work.missions.get(invocation.mission_ref)
            if mission is None:
                raise WorkflowStateError(f"unknown Workflow Mission: {invocation.mission_ref}")
            assets = work.assets.list_for_mission(invocation.mission_ref)
        return InvocationDelivery(
            invocation=invocation,
            mission=MissionProjection(
                mission_ref=mission.mission_ref,
                name=mission.name,
                metadata=mission.metadata,
            ),
            allowed_assets=tuple(asset.asset_ref for asset in assets),
            allowed_addresses=tuple(asset.primary_address for asset in assets),
            assets=tuple(
                AssetProjection(
                    asset_ref=asset.asset_ref,
                    primary_address=asset.primary_address,
                    metadata=asset.metadata,
                )
                for asset in assets
            ),
        )

    def _reconcile_active_step(
        self, workflow: WorkflowRun, step: WorkflowStepRun
    ) -> WorkflowStepRun | None:
        run_ref = step.capability_run_ref
        if run_ref is None:
            raise WorkflowStateError(f"active step has no CapabilityRunRef: {step.step_id}")
        with self._database.unit_of_work() as work:
            ingestion = work.result_ingestions.get(run_ref)
        if ingestion is None or not ingestion.status.is_complete:
            return None
        if ingestion.status is ResultIngestionStatus.REJECTED:
            self._mark_failed(
                workflow.workflow_run_ref,
                step.step_id,
                f"Result ingestion was rejected: {ingestion.error or 'no detail'}",
            )
            return self._required_step(workflow.workflow_run_ref, step.step_id)

        result = ingestion.result
        if result.execution_status is not CapabilityRunStatus.COMPLETED:
            self._mark_failed(
                workflow.workflow_run_ref,
                step.step_id,
                f"Capability execution ended with {result.execution_status.value}",
            )
            return self._required_step(workflow.workflow_run_ref, step.step_id)
        if not step.definition.success_policy.accepts(result.outcome.category):
            self._mark_failed(
                workflow.workflow_run_ref,
                step.step_id,
                f"Capability outcome {result.outcome.category.value} is not accepted by "
                f"{step.definition.success_policy.value}",
            )
            return self._required_step(workflow.workflow_run_ref, step.step_id)

        now = self._now()
        with self._database.unit_of_work() as work:
            return work.workflow_steps.finish(
                workflow.workflow_run_ref,
                step.step_id,
                WorkflowStepStatus.COMPLETED,
                updated_at=now,
            )

    def _complete_workflow(self, workflow_ref: WorkflowRunRef) -> WorkflowExecution:
        with self._database.unit_of_work() as work:
            work.workflows.set_status(
                workflow_ref,
                WorkflowStatus.COMPLETED,
                updated_at=self._now(),
            )
        return self._required_execution(workflow_ref)

    def _fail_from_terminal_step(
        self, execution: WorkflowExecution, step: WorkflowStepRun
    ) -> WorkflowExecution:
        if execution.run.status is WorkflowStatus.CANCELLED:
            return execution
        return self._mark_failed(
            execution.run.workflow_run_ref,
            step.step_id,
            step.failure_reason or f"Workflow step ended with {step.status.value}",
        )

    def _mark_failed(
        self, workflow_ref: WorkflowRunRef, step_id: str, reason: str
    ) -> WorkflowExecution:
        now = self._now()
        with self._database.unit_of_work() as work:
            work.workflow_steps.finish(
                workflow_ref,
                step_id,
                WorkflowStepStatus.FAILED,
                updated_at=now,
                failure_reason=reason,
            )
            work.workflows.set_status(
                workflow_ref,
                WorkflowStatus.FAILED,
                updated_at=now,
                failure_reason=reason,
            )
        return self._required_execution(workflow_ref)

    def _required_step(self, workflow_ref: WorkflowRunRef, step_id: str) -> WorkflowStepRun:
        with self._database.unit_of_work() as work:
            step = work.workflow_steps.get(workflow_ref, step_id)
        if step is None:
            raise WorkflowStateError(f"missing Workflow step: {workflow_ref}/{step_id}")
        return step

    def _required_execution(self, workflow_ref: WorkflowRunRef) -> WorkflowExecution:
        execution = self.inspect(workflow_ref)
        if execution is None:
            raise WorkflowNotFound(f"unknown WorkflowRun: {workflow_ref}")
        return execution

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Workflow clock must return a timezone-aware datetime")
        return value

    def _require_router(self) -> CapabilityRouter:
        if self._router is None:
            raise WorkflowStateError("Workflow dispatch requires a configured CapabilityRouter")
        return self._router


def capability_run_ref_for_step(workflow_ref: WorkflowRunRef, step_id: str) -> CapabilityRunRef:
    """Return the stable one-to-one CapabilityRun identity for a Workflow Step Run."""

    value = uuid5(_STEP_RUN_NAMESPACE, f"{workflow_ref}\0{step_id}")
    return CapabilityRunRef(f"run:{value}")
