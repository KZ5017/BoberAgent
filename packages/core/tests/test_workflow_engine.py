"""Durable deterministic Workflow execution and restart reconciliation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    AssetRef,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    WorkflowRunRef,
)
from boberagent_core import (
    Asset,
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    DatabaseConfig,
    Mission,
    ResultIngestionService,
    WorkflowDefinition,
    WorkflowService,
    WorkflowStatus,
    WorkflowStepDefinition,
    WorkflowStepStatus,
    WorkflowStepSuccessPolicy,
    upgrade_database,
)
from boberagent_transport import (
    CapabilityTransport,
    DeliveryAcknowledgement,
    InvocationDelivery,
    NodeAdvertisement,
    TransportFailure,
    TransportMessageId,
    invocation_message_id,
)
from pydantic import ValidationError
from test_capability_registry import MutableClock, advertisement, capability_definition

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
MISSION_REF = MissionRef("mission-workflow-engine")


class RecordingTransport(CapabilityTransport):
    def __init__(self) -> None:
        self.submissions: list[tuple[str, InvocationDelivery]] = []

    @property
    def connected(self) -> bool:
        return True

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def discover_node(self, node_id: str) -> NodeAdvertisement:
        raise KeyError(node_id)

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId:
        self.submissions.append((node_id, delivery))
        return invocation_message_id(delivery.invocation.run_id)

    async def flush_outboxes(self, node_id: str) -> int:
        del node_id
        return 0

    async def query_run_status(
        self, node_id: str, run_ref: CapabilityRunRef
    ) -> CapabilityRunStatus | None:
        del node_id, run_ref
        return None

    async def receive(self) -> bytes:
        raise RuntimeError("RecordingTransport has no outbound messages")

    async def acknowledge(self, acknowledgement: DeliveryAcknowledgement) -> None:
        del acknowledgement

    async def receive_failure(self) -> TransportFailure:
        raise RuntimeError("RecordingTransport has no failures")


def _seed_mission(database: CoreDatabase) -> None:
    with database.unit_of_work() as work:
        work.missions.add(
            Mission(
                mission_ref=MISSION_REF,
                status="ACTIVE",
                created_at=NOW,
                name="Workflow test mission",
            )
        )
        work.assets.add(
            Asset(
                asset_ref=AssetRef("asset-workflow-engine"),
                mission_ref=MISSION_REF,
                kind="host",
                primary_address="192.0.2.80",
                created_at=NOW,
            )
        )


def _definition(
    *,
    steps: int = 2,
    success_policy: WorkflowStepSuccessPolicy = WorkflowStepSuccessPolicy.SUCCESS_ONLY,
) -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id="procedure.test.sequential",
        version="1",
        steps=tuple(
            WorkflowStepDefinition(
                step_id=f"step-{index}",
                capability_id="test.registry_capability",
                operation=("discover" if index == 1 else "assess"),
                inputs={"sequence": index},
                success_policy=success_policy,
            )
            for index in range(1, steps + 1)
        ),
    )


def _runtime(
    database: CoreDatabase,
    transport: RecordingTransport,
    *,
    refresh: bool = True,
) -> tuple[CapabilityRegistry, WorkflowService]:
    clock = MutableClock(NOW)
    registry = CapabilityRegistry(database, clock=clock)
    if refresh:
        definition = capability_definition(operations=("discover", "assess"))
        registry.register_or_refresh_node(advertisement("node-workflow", definitions=(definition,)))
    router = CapabilityRouter(registry, transport, clock=clock)
    return registry, WorkflowService(database, router, clock=clock)


def _ingest(
    database: CoreDatabase,
    run_ref: CapabilityRunRef,
    *,
    execution_status: CapabilityRunStatus = CapabilityRunStatus.COMPLETED,
    outcome: CapabilityOutcomeCategory = CapabilityOutcomeCategory.SUCCESS,
) -> None:
    ingestion = ResultIngestionService(database, clock=lambda: NOW)
    ingestion.accept_result(
        CapabilityResult(
            run_ref=run_ref,
            execution_status=execution_status,
            outcome=CapabilityOutcome(category=outcome),
        )
    )
    assert ingestion.process_ingestion(run_ref).status.is_complete


def test_definition_requires_unique_stable_step_ids() -> None:
    step = WorkflowStepDefinition(
        step_id="duplicate",
        capability_id="test.registry_capability",
        operation="discover",
    )
    with pytest.raises(ValidationError, match="identifiers must be unique"):
        WorkflowDefinition(
            definition_id="procedure.test.invalid",
            version="1",
            steps=(step, step),
        )


def test_two_step_workflow_is_sequential_idempotent_and_routed(
    database: CoreDatabase,
) -> None:
    _seed_mission(database)
    transport = RecordingTransport()
    registry, workflows = _runtime(database, transport)
    workflow_ref = WorkflowRunRef("workflow-two-step")

    started = asyncio.run(
        workflows.start(
            _definition(),
            MISSION_REF,
            workflow_run_ref=workflow_ref,
        )
    )
    assert started.run.status is WorkflowStatus.RUNNING
    assert [step.status for step in started.steps] == [
        WorkflowStepStatus.ACTIVE,
        WorkflowStepStatus.PENDING,
    ]
    assert len(transport.submissions) == 1
    first_run = started.steps[0].capability_run_ref
    assert first_run is not None
    assert transport.submissions[0][1].invocation.workflow_run_ref == workflow_ref
    assert transport.submissions[0][1].allowed_assets == ("asset-workflow-engine",)

    still_waiting = asyncio.run(workflows.advance(workflow_ref))
    assert still_waiting.steps[0].status is WorkflowStepStatus.ACTIVE
    assert len(transport.submissions) == 1

    _ingest(database, first_run)
    second_active = asyncio.run(workflows.advance(workflow_ref))
    assert [step.status for step in second_active.steps] == [
        WorkflowStepStatus.COMPLETED,
        WorkflowStepStatus.ACTIVE,
    ]
    assert len(transport.submissions) == 2
    second_run = second_active.steps[1].capability_run_ref
    assert second_run is not None and second_run != first_run
    assert registry.routing_decision_for_run(first_run) is not None
    assert registry.routing_decision_for_run(second_run) is not None

    _ingest(database, second_run)
    completed = asyncio.run(workflows.advance(workflow_ref))
    assert completed.run.status is WorkflowStatus.COMPLETED
    assert all(step.status is WorkflowStepStatus.COMPLETED for step in completed.steps)
    assert len(transport.submissions) == 2


def test_restart_between_dispatch_and_result_does_not_redispatch(
    database_path: Path,
) -> None:
    first_database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(first_database)
    _seed_mission(first_database)
    first_transport = RecordingTransport()
    _registry, first_workflows = _runtime(first_database, first_transport)
    workflow_ref = WorkflowRunRef("workflow-restart-active")
    active = asyncio.run(
        first_workflows.start(
            _definition(steps=1),
            MISSION_REF,
            workflow_run_ref=workflow_ref,
        )
    )
    run_ref = active.steps[0].capability_run_ref
    assert run_ref is not None and len(first_transport.submissions) == 1
    first_database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(reopened)
    second_transport = RecordingTransport()
    _registry, resumed_workflows = _runtime(reopened, second_transport, refresh=False)
    try:
        waiting = asyncio.run(resumed_workflows.resume(workflow_ref))
        assert waiting.steps[0].status is WorkflowStepStatus.ACTIVE
        assert second_transport.submissions == []

        _ingest(reopened, run_ref)
        completed = asyncio.run(resumed_workflows.resume(workflow_ref))
        assert completed.run.status is WorkflowStatus.COMPLETED
        assert second_transport.submissions == []
    finally:
        reopened.dispose()


def test_restart_after_first_result_dispatches_only_second_step(
    database_path: Path,
) -> None:
    first_database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(first_database)
    _seed_mission(first_database)
    first_transport = RecordingTransport()
    _registry, first_workflows = _runtime(first_database, first_transport)
    workflow_ref = WorkflowRunRef("workflow-restart-between-steps")
    active = asyncio.run(
        first_workflows.start(_definition(), MISSION_REF, workflow_run_ref=workflow_ref)
    )
    first_run = active.steps[0].capability_run_ref
    assert first_run is not None
    _ingest(first_database, first_run)
    first_database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(reopened)
    second_transport = RecordingTransport()
    _registry, resumed_workflows = _runtime(reopened, second_transport)
    try:
        resumed = asyncio.run(resumed_workflows.resume(workflow_ref))
        assert [step.status for step in resumed.steps] == [
            WorkflowStepStatus.COMPLETED,
            WorkflowStepStatus.ACTIVE,
        ]
        assert len(second_transport.submissions) == 1
        assert second_transport.submissions[0][1].invocation.operation == "assess"
    finally:
        reopened.dispose()


@pytest.mark.parametrize(
    ("execution_status", "outcome", "reason"),
    [
        (CapabilityRunStatus.FAILED, CapabilityOutcomeCategory.UNKNOWN, "FAILED"),
        (CapabilityRunStatus.TIMED_OUT, CapabilityOutcomeCategory.UNKNOWN, "TIMED_OUT"),
        (CapabilityRunStatus.CANCELLED, CapabilityOutcomeCategory.UNKNOWN, "CANCELLED"),
        (CapabilityRunStatus.COMPLETED, CapabilityOutcomeCategory.NEGATIVE, "NEGATIVE"),
        (CapabilityRunStatus.COMPLETED, CapabilityOutcomeCategory.UNKNOWN, "UNKNOWN"),
        (CapabilityRunStatus.COMPLETED, CapabilityOutcomeCategory.PARTIAL, "PARTIAL"),
    ],
)
def test_unacceptable_execution_or_semantic_result_fails_workflow(
    database: CoreDatabase,
    execution_status: CapabilityRunStatus,
    outcome: CapabilityOutcomeCategory,
    reason: str,
) -> None:
    _seed_mission(database)
    transport = RecordingTransport()
    _registry, workflows = _runtime(database, transport)
    active = asyncio.run(workflows.start(_definition(steps=1), MISSION_REF))
    run_ref = active.steps[0].capability_run_ref
    assert run_ref is not None
    _ingest(
        database,
        run_ref,
        execution_status=execution_status,
        outcome=outcome,
    )

    failed = asyncio.run(workflows.advance(active.run.workflow_run_ref))
    assert failed.run.status is WorkflowStatus.FAILED
    assert failed.steps[0].status is WorkflowStepStatus.FAILED
    assert reason in (failed.run.failure_reason or "")
    assert len(transport.submissions) == 1


def test_explicit_negative_policy_advances_to_completion(database: CoreDatabase) -> None:
    _seed_mission(database)
    transport = RecordingTransport()
    _registry, workflows = _runtime(database, transport)
    active = asyncio.run(
        workflows.start(
            _definition(
                steps=1,
                success_policy=WorkflowStepSuccessPolicy.SUCCESS_OR_NEGATIVE,
            ),
            MISSION_REF,
        )
    )
    run_ref = active.steps[0].capability_run_ref
    assert run_ref is not None
    _ingest(database, run_ref, outcome=CapabilityOutcomeCategory.NEGATIVE)

    completed = asyncio.run(workflows.advance(active.run.workflow_run_ref))
    assert completed.run.status is WorkflowStatus.COMPLETED


def test_cancel_is_durable_and_does_not_claim_remote_run_cancellation(
    database: CoreDatabase,
) -> None:
    _seed_mission(database)
    transport = RecordingTransport()
    _registry, workflows = _runtime(database, transport)
    active = asyncio.run(workflows.start(_definition(), MISSION_REF))
    run_ref = active.steps[0].capability_run_ref
    assert run_ref is not None

    cancelled = workflows.cancel(active.run.workflow_run_ref)
    assert cancelled.run.status is WorkflowStatus.CANCELLED
    assert all(step.status is WorkflowStepStatus.CANCELLED for step in cancelled.steps)
    with database.unit_of_work() as work:
        capability_run = work.runs.get(run_ref)
    assert capability_run is not None
    assert capability_run.status is CapabilityRunStatus.CREATED
