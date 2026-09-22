"""Real in-process MCP Streamable HTTP coverage for durable human interaction."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityRunRef,
    CapabilityRunStatus,
    InteractionType,
    MissionRef,
)
from boberagent_core import (
    CoreDatabase,
    CoreInteractionService,
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
from boberagent_transport import InvocationDelivery, MissionProjection
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpServerConfiguration,
    McpTransport,
    McpTransportServer,
)
from pydantic import SecretStr
from transport_test_capability import interaction_capability_manifest

MISSION_REF = MissionRef("mission-hitl-mcp")
RUN_REF = CapabilityRunRef("run-hitl-mcp")


def test_mcp_request_response_resume_and_result_delivery(tmp_path: Path) -> None:
    capability = tmp_path / "capability"
    capability.mkdir()
    (capability / "capability.json").write_text(
        json.dumps(interaction_capability_manifest(), indent=2), encoding="utf-8"
    )
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    node = ExecutionNode(
        NodeConfiguration.for_runtime_directory(
            tmp_path / "node",
            capability_paths=(capability,),
            configured_node_id="node-hitl-mcp",
        )
    )

    async def receive_all(client: CoreTransportClient, transport: McpTransport) -> int:
        count = await client.flush_node("node-hitl-mcp")
        for _ in range(count):
            await client.receive_one()
        return count

    async def wait_for(status: CapabilityRunStatus, transport: McpTransport) -> None:
        for _ in range(200):
            if await transport.query_run_status("node-hitl-mcp", RUN_REF) is status:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"Run did not reach {status.value}")

    async def scenario() -> None:
        await node.initialize()
        server = McpTransportServer(
            endpoint=ExecutionNodeTransportEndpoint(node),
            configuration=McpServerConfiguration(
                port=0,
                bearer_token=SecretStr("hitl-test-token"),
            ),
        )
        await server.start()
        transport = McpTransport(
            McpClientConfiguration(
                endpoint_url=server.endpoint_url,
                node_id="node-hitl-mcp",
                bearer_token=SecretStr("hitl-test-token"),
            )
        )
        receiver = CoreTransportReceiver(database)
        client = CoreTransportClient(transport, receiver)
        try:
            await transport.connect()
            await transport.submit_invocation(
                "node-hitl-mcp",
                InvocationDelivery(
                    invocation=CapabilityInvocation(
                        run_id=RUN_REF,
                        capability_id="test.human_interaction",
                        operation="run",
                        mission_ref=MISSION_REF,
                        inputs={},
                    ),
                    mission=MissionProjection(mission_ref=MISSION_REF),
                ),
            )
            interactions = CoreInteractionService(database, transport)
            values: tuple[bool | str, ...] = (True, "mcp-safe-text", "normal")
            types = (
                InteractionType.CONFIRMATION,
                InteractionType.TEXT,
                InteractionType.SINGLE_CHOICE,
            )
            for expected_type, value in zip(types, values, strict=True):
                await wait_for(CapabilityRunStatus.WAITING_INPUT, transport)
                assert await receive_all(client, transport) > 0
                pending = interactions.list_pending()
                assert len(pending) == 1
                assert pending[0].request.interaction_type is expected_type
                await interactions.respond(pending[0].request.interaction_id, value)
            await wait_for(CapabilityRunStatus.COMPLETED, transport)
            assert await receive_all(client, transport) > 0
            result = receiver.result_for_run(RUN_REF)
            assert result is not None
            assert result.result.execution_status is CapabilityRunStatus.COMPLETED
            assert not interactions.list_pending()
        finally:
            await transport.disconnect()
            await server.stop()
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
