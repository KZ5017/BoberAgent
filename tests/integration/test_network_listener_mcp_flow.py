"""Incoming Session delivery through the unchanged real MCP carrier."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
    SessionRef,
)
from boberagent_core import CoreDatabase, CoreTransportClient, CoreTransportReceiver, DatabaseConfig
from boberagent_core.persistence.migrations import upgrade_database
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_transport import InvocationDelivery, MissionProjection
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpServerConfiguration,
    McpTransport,
    McpTransportServer,
)
from pydantic import SecretStr

CAPABILITY_ROOT = Path(__file__).resolve().parents[2] / "capabilities" / "network-listener"
MISSION_REF = MissionRef("mission-listener-mcp")
HOST = "127.0.0.1"


def _delivery(run_id: str, operation: str, inputs: JsonObject) -> InvocationDelivery:
    return InvocationDelivery(
        invocation=CapabilityInvocation(
            run_id=CapabilityRunRef(run_id),
            capability_id="network.listener",
            operation=operation,
            mission_ref=MISSION_REF,
            inputs=inputs,
        ),
        mission=MissionProjection(mission_ref=MISSION_REF, name="Listener MCP integration"),
        allowed_addresses=(HOST,),
    )


def test_listener_session_event_and_bytes_cross_real_mcp(tmp_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    receiver = CoreTransportReceiver(database)
    token = SecretStr("listener-mcp-token")

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(
                tmp_path / "node",
                capability_paths=(CAPABILITY_ROOT,),
                configured_node_id="node-listener-mcp",
            )
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        server = McpTransportServer(
            endpoint=endpoint,
            configuration=McpServerConfiguration(port=0, bearer_token=token),
        )
        await server.start()
        transport = McpTransport(
            McpClientConfiguration(
                endpoint_url=server.endpoint_url,
                node_id=endpoint.node_id,
                bearer_token=token,
            )
        )
        client = CoreTransportClient(transport, receiver)

        async def execute(delivery: InvocationDelivery) -> CapabilityResult:
            await client.submit_invocation(endpoint.node_id, delivery)
            for _ in range(200):
                status = await transport.query_run_status(
                    endpoint.node_id, delivery.invocation.run_id
                )
                if status is not None and status.is_terminal:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("MCP listener Run did not become terminal")
            count = await client.flush_node(endpoint.node_id)
            for _ in range(count):
                await client.receive_one()
            envelope = receiver.result_for_run(delivery.invocation.run_id)
            assert envelope is not None
            return envelope.result

        try:
            await transport.connect()
            advertisement = await client.discover_node(endpoint.node_id)
            assert any(
                str(definition.capability_id) == "network.listener"
                for definition in advertisement.capabilities
            )
            open_run = CapabilityRunRef("run-listener-mcp-open")
            opened = await execute(
                _delivery(
                    str(open_run),
                    "open",
                    {
                        "bind_address": HOST,
                        "port": 0,
                        "allowed_remote_addresses": [HOST],
                    },
                )
            )
            resource = opened.resources[0]
            port = resource.lifecycle_metadata["bound_port"]
            assert isinstance(port, int)
            reader, writer = await asyncio.open_connection(HOST, port)

            assert node.store is not None
            for _ in range(100):
                sessions = node.store.list_sessions_for_resource(resource.resource_id)
                if sessions:
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("MCP listener did not accept incoming Session")
            session_ref = SessionRef(sessions[0].descriptor.session_id)
            count = await client.flush_node(endpoint.node_id)
            for _ in range(count):
                await client.receive_one()
            assert any(
                envelope.event.type == "session.created"
                and envelope.event.payload["session_ref"] == str(session_ref)
                for envelope in receiver.events_for_run(open_run)
            )

            writer.write(b"mcp-ping")
            await writer.drain()
            received = await execute(
                _delivery(
                    "run-listener-mcp-receive",
                    "receive",
                    {"session_ref": str(session_ref), "max_bytes": 32, "timeout_seconds": 2},
                )
            )
            encoded = received.outcome.details["payload_base64"]
            assert isinstance(encoded, str)
            assert base64.b64decode(encoded) == b"mcp-ping"

            await execute(
                _delivery(
                    "run-listener-mcp-send",
                    "send",
                    {
                        "session_ref": str(session_ref),
                        "payload_base64": base64.b64encode(b"mcp-pong").decode(),
                    },
                )
            )
            assert await asyncio.wait_for(reader.readexactly(8), timeout=1) == b"mcp-pong"
            await execute(
                _delivery(
                    "run-listener-mcp-close",
                    "close_listener",
                    {"resource_ref": str(resource.resource_id)},
                )
            )
            assert await asyncio.wait_for(reader.read(), timeout=1) == b""
            writer.close()
            await writer.wait_closed()
        finally:
            await transport.disconnect()
            await server.stop()
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
