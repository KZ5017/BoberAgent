"""M14 incoming Session flow through Registry, Router, transport, and a real Node."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest
from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
    ResourceRef,
    SessionRef,
)
from boberagent_core import (
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    upgrade_database,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_transport import InMemoryTransport, InvocationDelivery, MissionProjection

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_ROOT = REPOSITORY_ROOT / "capabilities" / "network-listener"
MISSION_REF = MissionRef("mission-listener-integration")
HOST = "127.0.0.1"


def _delivery(
    run_id: str,
    operation: str,
    inputs: JsonObject,
    *,
    mission_ref: MissionRef = MISSION_REF,
) -> InvocationDelivery:
    invocation = CapabilityInvocation(
        run_id=CapabilityRunRef(run_id),
        capability_id="network.listener",
        operation=operation,
        mission_ref=mission_ref,
        inputs=inputs,
    )
    return InvocationDelivery(
        invocation=invocation,
        mission=MissionProjection(mission_ref=mission_ref, name="Listener integration"),
        allowed_addresses=(HOST,),
    )


async def _wait_for_session(node: ExecutionNode, resource_ref: ResourceRef) -> SessionRef:
    assert node.store is not None
    for _ in range(100):
        sessions = node.store.list_sessions_for_resource(resource_ref)
        if sessions:
            return sessions[0].descriptor.session_id
        await asyncio.sleep(0.01)
    raise AssertionError("incoming connection did not create a durable Session")


def test_listener_full_flow_uses_router_events_and_semantic_session_operations(
    tmp_path: Path,
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    registry = CapabilityRegistry(database)
    transport = InMemoryTransport(queue_capacity=100)
    receiver = CoreTransportReceiver(database)
    client = CoreTransportClient(transport, receiver)
    registration = CapabilityRegistrationClient(transport, registry)
    router = CapabilityRouter(registry, transport)

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(
                tmp_path / "node",
                capability_paths=(CAPABILITY_ROOT,),
                configured_node_id="node-listener-integration",
            )
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport.register_node(endpoint)
        await transport.connect()
        await registration.refresh_node(endpoint.node_id)

        async def execute(delivery: InvocationDelivery) -> CapabilityResult:
            selected = router.select_provider(
                capability_id=delivery.invocation.capability_id,
                operation=delivery.invocation.operation,
            )
            await router.dispatch(
                invocation=delivery.invocation,
                delivery=delivery,
                provider=selected,
            )
            await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
            count = await client.flush_node(endpoint.node_id)
            for _ in range(count):
                await client.receive_one()
            envelope = receiver.result_for_run(delivery.invocation.run_id)
            assert envelope is not None
            return envelope.result

        try:
            open_run = CapabilityRunRef("run-listener-open")
            opened = await execute(
                _delivery(
                    str(open_run),
                    "open",
                    {
                        "bind_address": HOST,
                        "port": 0,
                        "allowed_remote_addresses": [HOST],
                        "max_sessions": 2,
                    },
                )
            )
            assert opened.outcome.code == "LISTENER_OPENED"
            assert opened.sessions == ()
            resource = opened.resources[0]
            port = resource.lifecycle_metadata["bound_port"]
            assert isinstance(port, int) and port > 0

            reader, writer = await asyncio.open_connection(HOST, port)
            session_ref = await _wait_for_session(node, resource.resource_id)
            count = await client.flush_node(endpoint.node_id)
            for _ in range(count):
                await client.receive_one()
            created_events = tuple(
                envelope.event
                for envelope in receiver.events_for_run(open_run)
                if envelope.event.type == "session.created"
            )
            assert len(created_events) == 1
            assert created_events[0].payload["session_ref"] == str(session_ref)
            assert created_events[0].payload["resource_ref"] == str(resource.resource_id)
            assert created_events[0].payload["remote_address"] == HOST

            writer.write(b"hello\x00from-peer")
            await writer.drain()
            received = await execute(
                _delivery(
                    "run-listener-receive",
                    "receive",
                    {"session_ref": str(session_ref), "max_bytes": 64, "timeout_seconds": 2},
                )
            )
            encoded = received.outcome.details["payload_base64"]
            assert isinstance(encoded, str)
            assert base64.b64decode(encoded) == b"hello\x00from-peer"

            sent = await execute(
                _delivery(
                    "run-listener-send",
                    "send",
                    {
                        "session_ref": str(session_ref),
                        "payload_base64": base64.b64encode(b"hello\x00from-node").decode(),
                        "timeout_seconds": 2,
                    },
                )
            )
            assert sent.outcome.code == "STREAM_BYTES_SENT"
            assert await asyncio.wait_for(reader.readexactly(15), timeout=1) == (
                b"hello\x00from-node"
            )

            wrong_mission = await execute(
                _delivery(
                    "run-listener-wrong-mission",
                    "receive",
                    {"session_ref": str(session_ref), "max_bytes": 1, "timeout_seconds": 1},
                    mission_ref=MissionRef("mission-listener-foreign"),
                )
            )
            assert wrong_mission.outcome.code == "SESSION_UNAVAILABLE"

            closed = await execute(
                _delivery(
                    "run-listener-close-session",
                    "close_session",
                    {"session_ref": str(session_ref)},
                )
            )
            assert closed.outcome.code == "STREAM_SESSION_CLOSED"
            assert await asyncio.wait_for(reader.read(), timeout=1) == b""
            writer.close()
            await writer.wait_closed()
            closed_again = await execute(
                _delivery(
                    "run-listener-close-session-again",
                    "close_session",
                    {"session_ref": str(session_ref)},
                )
            )
            assert closed_again.outcome.code == "STREAM_SESSION_ALREADY_CLOSED"
            unavailable = await execute(
                _delivery(
                    "run-listener-after-close",
                    "send",
                    {
                        "session_ref": str(session_ref),
                        "payload_base64": base64.b64encode(b"not-sent").decode(),
                    },
                )
            )
            assert unavailable.outcome.code == "SESSION_UNAVAILABLE"

            listener_closed = await execute(
                _delivery(
                    "run-listener-close-resource",
                    "close_listener",
                    {"resource_ref": str(resource.resource_id)},
                )
            )
            assert listener_closed.outcome.code == "LISTENER_CLOSED"
            listener_closed_again = await execute(
                _delivery(
                    "run-listener-close-resource-again",
                    "close_listener",
                    {"resource_ref": str(resource.resource_id)},
                )
            )
            assert listener_closed_again.outcome.code == "LISTENER_ALREADY_CLOSED"
            with pytest.raises((ConnectionError, OSError, TimeoutError)):
                await asyncio.wait_for(asyncio.open_connection(HOST, port), timeout=1)
            assert node.listener_runtime is not None
            assert node.listener_runtime.active_listener_count == 0
            assert node.listener_runtime.active_session_count == 0
            assert node.listener_runtime.active_accept_task_count == 0
        finally:
            await transport.disconnect()
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
