"""Durable Node interaction state, waiter, idempotency, and restart recovery."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from boberagent_contracts import (
    CapabilityRunRef,
    CapabilityRunStatus,
    InteractionLifecycle,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    InteractionType,
    MissionRef,
)
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.events import EventOutbox, NodeEventService
from boberagent_execution_node.interactions import InteractionConflict, InteractionRuntime
from boberagent_execution_node.persistence import RunRecord, RuntimeDatabase, RuntimeStore
from boberagent_execution_node.persistence.migrations import upgrade_database
from boberagent_sdk import ExecutionCancelled

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
RUN_REF = CapabilityRunRef("run-human-interaction")
MISSION_REF = MissionRef("mission-human-interaction")


def _request(*, mission_ref: MissionRef = MISSION_REF) -> InteractionRequest:
    return InteractionRequest(
        interaction_id=InteractionRef("interaction-confirm-runtime"),
        run_ref=RUN_REF,
        mission_ref=mission_ref,
        interaction_type=InteractionType.CONFIRMATION,
        title="Continue?",
        description="Confirm the harmless synthetic operation.",
        input_schema={"type": "boolean"},
        resume_semantics="same_run",
        requested_at=NOW,
    )


def _store(path: Path) -> tuple[RuntimeDatabase, RuntimeStore]:
    database = RuntimeDatabase(path)
    upgrade_database(database)
    store = RuntimeStore(database)
    store.add_run(
        RunRecord(
            run_ref=RUN_REF,
            mission_ref=MISSION_REF,
            capability_id="test.interactive",
            operation="run",
            status=CapabilityRunStatus.RUNNING,
            created_at=NOW,
            started_at=NOW,
        )
    )
    return database, store


def test_request_waits_durably_resumes_and_rejects_conflicting_response(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database, store = _store(tmp_path / "runtime.sqlite3")
        runtime = InteractionRuntime(store, clock=lambda: NOW)
        events = NodeEventService(
            outbox=EventOutbox(store),
            mission_ref=MISSION_REF,
            run_ref=RUN_REF,
            clock=lambda: NOW,
        )
        request = _request()
        task = asyncio.create_task(
            runtime.request(
                request,
                run_ref=RUN_REF,
                mission_ref=MISSION_REF,
                workflow_run_ref=None,
                events=events,
            )
        )
        await asyncio.sleep(0)
        persisted = store.get_interaction(request.interaction_id)
        assert persisted is not None
        assert persisted.state is InteractionLifecycle.REQUESTED
        assert store.get_run(RUN_REF).status is CapabilityRunStatus.WAITING_INPUT  # type: ignore[union-attr]
        assert [record.event.type for record in store.pending_events()] == ["interaction.requested"]

        response = InteractionResponse(
            interaction_ref=request.interaction_id,
            run_ref=RUN_REF,
            responded_at=NOW + timedelta(seconds=1),
            value=True,
        )
        accepted, duplicate = runtime.accept_response(response)
        assert not duplicate
        assert accepted.state is InteractionLifecycle.ANSWERED
        assert await task == response
        assert store.get_run(RUN_REF).status is CapabilityRunStatus.RUNNING  # type: ignore[union-attr]

        replay, duplicate = runtime.accept_response(response)
        assert duplicate and replay.response == response
        conflicting = response.model_copy(update={"value": False})
        with pytest.raises(InteractionConflict, match="different immutable response"):
            runtime.accept_response(conflicting)
        database.close()

    asyncio.run(scenario())


def test_cross_mission_and_late_responses_are_rejected(tmp_path: Path) -> None:
    database, store = _store(tmp_path / "runtime.sqlite3")
    runtime = InteractionRuntime(store, clock=lambda: NOW)
    with pytest.raises(ValueError, match="Mission"):
        store.begin_interaction(_request(mission_ref=MissionRef("mission-other")))

    request = _request()
    store.begin_interaction(request)
    runtime.cancel_for_run(RUN_REF, reason="Run cancelled")
    response = InteractionResponse(
        interaction_ref=request.interaction_id,
        run_ref=RUN_REF,
        responded_at=NOW + timedelta(seconds=1),
        value=True,
    )
    with pytest.raises(InteractionConflict, match="no longer answerable"):
        runtime.accept_response(response)
    database.close()


def test_node_restart_marks_waiting_run_failed_and_interaction_cancelled(tmp_path: Path) -> None:
    configuration = NodeConfiguration.for_runtime_directory(
        tmp_path / "node", configured_node_id="node-interaction-recovery"
    )

    async def scenario() -> None:
        first = ExecutionNode(configuration)
        await first.initialize()
        assert first.store is not None
        first.store.add_run(
            RunRecord(
                run_ref=RUN_REF,
                mission_ref=MISSION_REF,
                capability_id="test.interactive",
                operation="run",
                status=CapabilityRunStatus.RUNNING,
                created_at=NOW,
                started_at=NOW,
            )
        )
        first.store.begin_interaction(_request())
        assert first.database is not None
        first.database.close()  # simulate process loss; do not invoke graceful waiter release

        restarted = ExecutionNode(configuration)
        await restarted.initialize()
        assert restarted.store is not None
        run = restarted.store.get_run(RUN_REF)
        interaction = restarted.store.get_interaction(InteractionRef("interaction-confirm-runtime"))
        assert run is not None and run.status is CapabilityRunStatus.FAILED
        assert interaction is not None
        assert interaction.state is InteractionLifecycle.CANCELLED
        assert interaction.cancellation_reason is not None
        assert restarted.results is not None
        assert restarted.results.get(RUN_REF) is not None
        assert "interaction.cancelled" in {
            record.event.type for record in restarted.store.pending_events()
        }
        response = InteractionResponse(
            interaction_ref=interaction.request.interaction_id,
            run_ref=RUN_REF,
            responded_at=NOW + timedelta(seconds=1),
            value=True,
        )
        assert restarted.interaction_runtime is not None
        with pytest.raises(InteractionConflict, match="no longer answerable"):
            restarted.interaction_runtime.accept_response(response)
        await restarted.shutdown()

    asyncio.run(scenario())


def test_graceful_interaction_shutdown_releases_waiter(tmp_path: Path) -> None:
    async def scenario() -> None:
        database, store = _store(tmp_path / "runtime.sqlite3")
        runtime = InteractionRuntime(store, clock=lambda: NOW)
        events = NodeEventService(
            outbox=EventOutbox(store),
            mission_ref=MISSION_REF,
            run_ref=RUN_REF,
            clock=lambda: NOW,
        )
        task = asyncio.create_task(
            runtime.request(
                _request(),
                run_ref=RUN_REF,
                mission_ref=MISSION_REF,
                workflow_run_ref=None,
                events=events,
            )
        )
        await asyncio.sleep(0)
        assert runtime.shutdown() == 1
        with pytest.raises(ExecutionCancelled):
            await task
        database.close()

    asyncio.run(scenario())
