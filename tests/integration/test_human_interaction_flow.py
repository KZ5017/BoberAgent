"""M15 durable Core restart and in-memory transport interaction vertical slice."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    CapabilityRunStatus,
    InteractionResponse,
    InteractionType,
    MissionRef,
    WorkflowRunRef,
)
from boberagent_core import (
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    CoreInteractionService,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    Mission,
    ResultIngestionService,
    WorkflowDefinition,
    WorkflowService,
    WorkflowStatus,
    WorkflowStepDefinition,
    WorkflowStepStatus,
    upgrade_database,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_transport import (
    InMemoryTransport,
    InteractionResponseAcknowledgement,
    ProtocolError,
    TransportDisconnected,
)
from transport_test_capability import (
    InteractiveSyntheticCapability,
    interaction_capability_manifest,
)

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
MISSION_REF = MissionRef("mission-hitl-integration")
WORKFLOW_REF = WorkflowRunRef("workflow-hitl-integration")


class LoseFirstAcknowledgement:
    def __init__(self, delegate: InMemoryTransport) -> None:
        self._delegate = delegate
        self._lost = False

    async def submit_interaction_response(
        self, node_id: str, response: InteractionResponse
    ) -> InteractionResponseAcknowledgement:
        acknowledgement = await self._delegate.submit_interaction_response(node_id, response)
        if not self._lost:
            self._lost = True
            raise TransportDisconnected("simulated lost Interaction acknowledgement")
        return acknowledgement


def _configuration(root: Path) -> NodeConfiguration:
    capability = root / "capability"
    capability.mkdir(parents=True)
    (capability / "capability.json").write_text(
        json.dumps(interaction_capability_manifest(), indent=2), encoding="utf-8"
    )
    return NodeConfiguration.for_runtime_directory(
        root / "runtime",
        capability_paths=(capability,),
        configured_node_id="node-hitl-integration",
    )


def _open_core(path: Path) -> CoreDatabase:
    database = CoreDatabase(DatabaseConfig.sqlite(path))
    upgrade_database(database)
    return database


async def _receive_all(client: CoreTransportClient, node_id: str) -> int:
    count = await client.flush_node(node_id)
    for _ in range(count):
        await client.receive_one()
    return count


async def _wait_for_status(
    transport: InMemoryTransport,
    node_id: str,
    run_ref: object,
    expected: CapabilityRunStatus,
) -> None:
    for _ in range(200):
        status = await transport.query_run_status(node_id, run_ref)  # type: ignore[arg-type]
        if status is expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"CapabilityRun did not reach {expected.value}")


def test_core_restart_workflow_blocks_then_resumes_same_run(tmp_path: Path) -> None:
    InteractiveSyntheticCapability.execution_count = 0
    core_path = tmp_path / "core.sqlite3"
    core_a = _open_core(core_path)
    with core_a.unit_of_work() as work:
        work.missions.add(
            Mission(
                mission_ref=MISSION_REF,
                status="ACTIVE",
                created_at=NOW,
                name="HITL integration",
            )
        )
    transport = InMemoryTransport(queue_capacity=40)
    node = ExecutionNode(_configuration(tmp_path / "node"))

    async def scenario() -> None:
        nonlocal core_a
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport.register_node(endpoint)
        await transport.connect()

        registry_a = CapabilityRegistry(core_a)
        await CapabilityRegistrationClient(transport, registry_a).refresh_node(endpoint.node_id)
        router_a = CapabilityRouter(registry_a, transport)
        receiver_a = CoreTransportReceiver(core_a, result_ingestion=ResultIngestionService(core_a))
        client_a = CoreTransportClient(transport, receiver_a)
        workflows_a = WorkflowService(core_a, router_a)
        definition = WorkflowDefinition(
            definition_id="procedure.test.human_interaction",
            version="1",
            steps=(
                WorkflowStepDefinition(
                    step_id="ask-operator",
                    capability_id="test.human_interaction",
                    operation="run",
                    inputs={},
                ),
            ),
        )
        active = await workflows_a.start(definition, MISSION_REF, workflow_run_ref=WORKFLOW_REF)
        run_ref = active.steps[0].capability_run_ref
        assert run_ref is not None
        await _wait_for_status(
            transport, endpoint.node_id, run_ref, CapabilityRunStatus.WAITING_INPUT
        )
        assert await _receive_all(client_a, endpoint.node_id) >= 2
        pending_a = CoreInteractionService(core_a).list_pending()
        assert len(pending_a) == 1
        assert pending_a[0].request.interaction_type is InteractionType.CONFIRMATION
        blocked = await workflows_a.advance(WORKFLOW_REF)
        assert blocked.run.status is WorkflowStatus.RUNNING
        assert blocked.steps[0].status is WorkflowStepStatus.ACTIVE
        stable_run_ref = blocked.steps[0].capability_run_ref

        # Core disappears while the Node and suspended capability remain alive.
        core_a.dispose()
        core_b = _open_core(core_path)
        try:
            registry_b = CapabilityRegistry(core_b)
            await CapabilityRegistrationClient(transport, registry_b).refresh_node(endpoint.node_id)
            ingestion_b = ResultIngestionService(core_b)
            receiver_b = CoreTransportReceiver(core_b, result_ingestion=ingestion_b)
            client_b = CoreTransportClient(transport, receiver_b)
            interactions = CoreInteractionService(core_b, LoseFirstAcknowledgement(transport))
            restored = interactions.list_pending()
            assert len(restored) == 1
            assert restored[0].request.interaction_id == pending_a[0].request.interaction_id
            assert restored[0].request.run_ref == stable_run_ref

            with pytest.raises(TransportDisconnected):
                await interactions.respond(restored[0].request.interaction_id, True)
            response_intent = CoreInteractionService(core_b).get(restored[0].request.interaction_id)
            assert response_intent is not None and response_intent.response is not None
            answered = await interactions.respond(restored[0].request.interaction_id, True)
            assert answered.response == response_intent.response
            conflicting = response_intent.response.model_copy(update={"value": False})
            with pytest.raises(ProtocolError, match="rejected"):
                await transport.submit_interaction_response(endpoint.node_id, conflicting)
            await _wait_for_status(
                transport, endpoint.node_id, run_ref, CapabilityRunStatus.WAITING_INPUT
            )
            await _receive_all(client_b, endpoint.node_id)
            text_request = interactions.list_pending()
            assert len(text_request) == 1
            assert text_request[0].request.interaction_type is InteractionType.TEXT
            await interactions.respond(text_request[0].request.interaction_id, "harmless-id")

            await _wait_for_status(
                transport, endpoint.node_id, run_ref, CapabilityRunStatus.WAITING_INPUT
            )
            await _receive_all(client_b, endpoint.node_id)
            choice = interactions.list_pending()
            assert len(choice) == 1
            assert choice[0].request.interaction_type is InteractionType.SINGLE_CHOICE
            await interactions.respond(choice[0].request.interaction_id, "normal")

            await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
            await _receive_all(client_b, endpoint.node_id)
            completed = await WorkflowService(
                core_b, CapabilityRouter(registry_b, transport)
            ).advance(WORKFLOW_REF)
            assert completed.run.status is WorkflowStatus.COMPLETED
            assert completed.steps[0].capability_run_ref == stable_run_ref
            assert InteractiveSyntheticCapability.execution_count == 1
            assert not interactions.list_pending()
        finally:
            core_b.dispose()
        await transport.disconnect()
        await node.shutdown()

    asyncio.run(scenario())
