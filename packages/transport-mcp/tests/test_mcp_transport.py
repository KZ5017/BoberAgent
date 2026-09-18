"""Real loopback MCP carrier tests (no in-process MCP shortcut)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx2
import pytest
from boberagent_contracts import CapabilityInvocation, CapabilityRunRef, MissionRef
from boberagent_transport import (
    DeliveryAcknowledgement,
    InvocationDelivery,
    MissionProjection,
    NodeAdvertisement,
    ProtocolError,
    RunStatusResponse,
    TransportDisconnected,
    UnknownNode,
    parse_handshake_request,
    parse_invocation,
    parse_run_status_request,
    serialize_message,
)
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpConnectionState,
    McpServerConfiguration,
    McpTransport,
    McpTransportServer,
)
from pydantic import SecretStr, ValidationError


class StubEndpoint:
    node_id = "node-mcp-test"

    def __init__(self) -> None:
        self.invocations: list[bytes] = []
        self.execution_started = asyncio.Event()
        self.allow_completion = asyncio.Event()
        self.acknowledgements: list[bytes] = []

    async def handshake(self, request: bytes) -> bytes:
        parsed = parse_handshake_request(request)
        return serialize_message(
            NodeAdvertisement(
                request_message_id=parsed.message_id,
                node_id=self.node_id,
                timestamp=datetime.now(UTC),
                lifecycle="READY",
                database_ready=True,
                capabilities=(),
                capability_statuses=(),
            )
        )

    async def accept_invocation(self, message: bytes) -> None:
        parse_invocation(message)
        self.invocations.append(message)
        self.execution_started.set()
        await self.allow_completion.wait()

    async def pending_outbound(self) -> tuple[bytes, ...]:
        return ()

    async def query_run_status(self, message: bytes) -> bytes:
        request = parse_run_status_request(message)
        return serialize_message(
            RunStatusResponse(
                request_message_id=request.message_id,
                node_id=self.node_id,
                correlation_id=request.correlation_id,
                status=None,
            )
        )

    async def acknowledge(self, message: bytes) -> None:
        DeliveryAcknowledgement.model_validate_json(message)
        self.acknowledgements.append(message)


def _delivery(run_id: str = "run-mcp-test") -> InvocationDelivery:
    return InvocationDelivery(
        invocation=CapabilityInvocation(
            run_id=CapabilityRunRef(run_id),
            capability_id="test.mcp",
            operation="execute",
            mission_ref=MissionRef("mission-mcp-test"),
            inputs={},
        ),
        mission=MissionProjection(mission_ref=MissionRef("mission-mcp-test")),
    )


def test_real_streamable_http_handshake_and_async_submission() -> None:
    async def scenario() -> None:
        endpoint = StubEndpoint()
        token = SecretStr("unit-test-token")
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
        try:
            await transport.connect()
            assert transport.state is McpConnectionState.CONNECTED
            advertisement = await transport.discover_node(endpoint.node_id)
            assert advertisement.node_id == endpoint.node_id
            assert (
                await transport.query_run_status(endpoint.node_id, CapabilityRunRef("run-unknown"))
                is None
            )
            with pytest.raises(UnknownNode):
                await transport.discover_node("node-not-configured")
            with pytest.raises(ProtocolError, match="rejected"):
                await transport.send_serialized_invocation(endpoint.node_id, b"{not-json")
            assert endpoint.invocations == []
            message_id = await asyncio.wait_for(
                transport.submit_invocation(endpoint.node_id, _delivery()), timeout=1
            )
            assert str(message_id) == "transport-invocation:run-mcp-test"
            await asyncio.wait_for(endpoint.execution_started.wait(), timeout=1)
            assert len(endpoint.invocations) == 1
        finally:
            endpoint.allow_completion.set()
            await transport.disconnect()
            await server.stop()

    asyncio.run(scenario())


def test_missing_and_wrong_bearer_tokens_are_rejected() -> None:
    async def scenario() -> None:
        endpoint = StubEndpoint()
        server = McpTransportServer(
            endpoint=endpoint,
            configuration=McpServerConfiguration(port=0, bearer_token=SecretStr("correct-token")),
        )
        await server.start()
        async with httpx2.AsyncClient(trust_env=False) as unauthenticated:
            response = await unauthenticated.post(server.endpoint_url, json={})
            assert response.status_code == 401
        wrong = McpTransport(
            McpClientConfiguration(
                endpoint_url=server.endpoint_url,
                node_id=endpoint.node_id,
                bearer_token=SecretStr("wrong-token"),
            )
        )
        try:
            with pytest.raises(TransportDisconnected):
                await wrong.connect()
            assert wrong.state is McpConnectionState.DISCONNECTED
        finally:
            await wrong.disconnect()
            await server.stop()

    asyncio.run(scenario())


def test_insecure_remote_configuration_requires_explicit_override() -> None:
    with pytest.raises(ValidationError, match="plaintext MCP is restricted"):
        McpClientConfiguration(
            endpoint_url="http://192.0.2.10:8000/mcp",
            node_id="node-remote",
            bearer_token=SecretStr("token"),
        )
    with pytest.raises(ValidationError, match="non-loopback MCP listener"):
        McpServerConfiguration(
            bind_host="0.0.0.0",
            port=8000,
            bearer_token=SecretStr("token"),
        )


def test_bearer_token_is_redacted_from_configuration_representations() -> None:
    secret = "credential-that-must-not-leak"
    client = McpClientConfiguration(
        endpoint_url="http://127.0.0.1:8000/mcp",
        node_id="node-redaction",
        bearer_token=SecretStr(secret),
    )
    server = McpServerConfiguration(bearer_token=SecretStr(secret))
    assert secret not in repr(client)
    assert secret not in repr(server)
