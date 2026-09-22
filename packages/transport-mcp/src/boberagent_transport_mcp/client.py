"""Core-side MCP client implementing the neutral Capability transport protocol."""

from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
from contextlib import AsyncExitStack, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx2
from boberagent_contracts import (
    ArtifactDescriptor,
    CapabilityRunRef,
    CapabilityRunStatus,
    InteractionResponse,
)
from boberagent_transport import (
    MAX_PROTOCOL_CHUNK_BYTES,
    ArtifactChunk,
    ArtifactTransferAcknowledgement,
    ArtifactTransferFinalize,
    ArtifactTransferReady,
    ArtifactTransferRejection,
    ArtifactTransferStart,
    DeliveryAcknowledgement,
    HandshakeRequest,
    InteractionResponseAcknowledgement,
    InteractionResponseEnvelope,
    InvocationDelivery,
    InvocationEnvelope,
    NodeAdvertisement,
    ProtocolError,
    RunStatusRequest,
    TransportArtifactReceiver,
    TransportBackpressure,
    TransportDisconnected,
    TransportFailure,
    TransportMessageId,
    UnknownNode,
    artifact_chunk_message_id,
    artifact_finalize_message_id,
    artifact_start_message_id,
    artifact_transfer_id,
    ensure_supported_protocol,
    interaction_response_message_id,
    invocation_message_id,
    parse_advertisement,
    parse_artifact_response,
    parse_interaction_acknowledgement,
    parse_outbound,
    parse_run_status_response,
    serialize_message,
)
from mcp import Client
from mcp.client import Transport
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from .config import McpClientConfiguration
from .models import (
    ArtifactReadRequest,
    ArtifactReadResponse,
    ArtifactSyncSummary,
    McpConnectionState,
)


class McpTransport:
    """MCP carrier preserving BoberAgent envelope, outbox, and ack semantics."""

    def __init__(self, configuration: McpClientConfiguration) -> None:
        self.configuration = configuration
        self._state = McpConnectionState.DISCONNECTED
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue(configuration.outbound_queue_capacity)
        self._failures: asyncio.Queue[TransportFailure] = asyncio.Queue(
            configuration.outbound_queue_capacity
        )
        self._queued_outbound_ids: set[str] = set()

    @property
    def state(self) -> McpConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state is McpConnectionState.CONNECTED

    async def connect(self) -> None:
        if self.connected:
            return
        if self._state is McpConnectionState.CONNECTING:
            raise TransportDisconnected("MCP transport connection is already in progress")
        self._state = McpConnectionState.CONNECTING
        stack = AsyncExitStack()
        try:
            verification: bool | str | ssl.SSLContext
            if isinstance(self.configuration.verify_tls, Path):
                verification = str(self.configuration.verify_tls)
            else:
                verification = self.configuration.verify_tls
            http_client = await stack.enter_async_context(
                httpx2.AsyncClient(
                    headers={
                        "Authorization": (
                            f"Bearer {self.configuration.bearer_token.get_secret_value()}"
                        )
                    },
                    timeout=self.configuration.request_timeout_seconds,
                    verify=verification,
                    trust_env=False,
                )
            )
            transport = cast(
                Transport,
                streamable_http_client(self.configuration.endpoint_url, http_client=http_client),
            )
            client = await stack.enter_async_context(
                Client(
                    transport,
                    read_timeout_seconds=self.configuration.request_timeout_seconds,
                )
            )
        except Exception as error:
            await stack.aclose()
            self._state = McpConnectionState.DISCONNECTED
            raise TransportDisconnected(
                f"MCP connection failed: {type(error).__name__}",
                node_id=self.configuration.node_id,
            ) from error
        self._stack = stack
        self._client = client
        self._state = McpConnectionState.CONNECTED

    async def disconnect(self) -> None:
        stack = self._stack
        self._client = None
        self._stack = None
        self._state = McpConnectionState.DISCONNECTED
        if stack is not None:
            await stack.aclose()

    async def discover_node(self, node_id: str) -> NodeAdvertisement:
        self._validate_target(node_id)
        request = HandshakeRequest(
            message_id=TransportMessageId(f"transport-handshake:{uuid4()}"),
            node_id=node_id,
            timestamp=datetime.now(UTC),
        )
        response = await self._call_text(
            "boberagent.handshake", {"payload": serialize_message(request).decode("utf-8")}
        )
        advertisement = parse_advertisement(response.encode("utf-8"))
        ensure_supported_protocol(advertisement.protocol_version)
        if advertisement.node_id != node_id:
            raise UnknownNode("MCP handshake returned a different Node", node_id=node_id)
        return advertisement

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId:
        self._validate_target(node_id)
        envelope = InvocationEnvelope(
            message_id=invocation_message_id(delivery.invocation.run_id),
            node_id=node_id,
            correlation_id=delivery.invocation.run_id,
            timestamp=datetime.now(UTC),
            delivery=delivery,
        )
        response = await self._call_text(
            "boberagent.submit_invocation",
            {"payload": serialize_message(envelope).decode("utf-8")},
        )
        if response != str(envelope.message_id):
            raise ProtocolError("MCP invocation acceptance identity mismatch", node_id=node_id)
        return envelope.message_id

    async def send_serialized_invocation(self, node_id: str, message: bytes) -> str:
        """Protocol-test hook that still crosses MCP and the Node validation boundary."""

        self._validate_target(node_id)
        try:
            payload = message.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProtocolError("serialized invocation is not UTF-8 JSON") from error
        return await self._call_text(
            "boberagent.submit_invocation",
            {"payload": payload},
        )

    async def flush_outboxes(self, node_id: str) -> int:
        self._validate_target(node_id)
        result = await self._call_value(
            "boberagent.poll_outbound",
            {"limit": self.configuration.poll_batch_size},
        )
        messages = _string_list(result, "outbound messages")
        queued = 0
        for value in messages:
            serialized = value.encode("utf-8")
            envelope = parse_outbound(serialized)
            if envelope.node_id != node_id:
                raise ProtocolError("MCP outbound message identifies another Node")
            identity = str(envelope.message_id)
            if identity in self._queued_outbound_ids:
                continue
            try:
                self._outbound.put_nowait(serialized)
            except asyncio.QueueFull as error:
                raise TransportBackpressure("MCP outbound queue is full") from error
            self._queued_outbound_ids.add(identity)
            queued += 1
        await self._poll_failures()
        return queued

    async def query_run_status(
        self, node_id: str, run_ref: CapabilityRunRef
    ) -> CapabilityRunStatus | None:
        self._validate_target(node_id)
        request = RunStatusRequest(
            message_id=TransportMessageId(f"transport-run-status:{uuid4()}"),
            node_id=node_id,
            correlation_id=run_ref,
            timestamp=datetime.now(UTC),
        )
        raw = await self._call_text(
            "boberagent.query_run_status",
            {"payload": serialize_message(request).decode("utf-8")},
        )
        response = parse_run_status_response(raw.encode("utf-8"))
        if (
            response.request_message_id != request.message_id
            or response.node_id != node_id
            or response.correlation_id != run_ref
        ):
            raise ProtocolError("MCP Run status response does not match its request")
        return response.status

    async def submit_interaction_response(
        self, node_id: str, response: InteractionResponse
    ) -> InteractionResponseAcknowledgement:
        self._validate_target(node_id)
        envelope = InteractionResponseEnvelope(
            message_id=interaction_response_message_id(response.interaction_ref),
            node_id=node_id,
            correlation_id=response.run_ref,
            timestamp=datetime.now(UTC),
            response=response,
        )
        raw = await self._call_text(
            "boberagent.interaction.respond",
            {"payload": serialize_message(envelope).decode("utf-8")},
        )
        acknowledgement = parse_interaction_acknowledgement(raw.encode("utf-8"))
        if (
            acknowledgement.request_message_id != envelope.message_id
            or acknowledgement.node_id != node_id
            or acknowledgement.correlation_id != response.run_ref
            or acknowledgement.interaction_ref != response.interaction_ref
        ):
            raise ProtocolError("MCP Interaction acknowledgement does not match its response")
        return acknowledgement

    async def receive(self) -> bytes:
        self._require_client()
        message = await self._outbound.get()
        envelope = parse_outbound(message)
        self._queued_outbound_ids.discard(str(envelope.message_id))
        self._outbound.task_done()
        return message

    async def acknowledge(self, acknowledgement: DeliveryAcknowledgement) -> None:
        self._validate_target(acknowledgement.node_id)
        await self._call_value(
            "boberagent.acknowledge",
            {"payload": serialize_message(acknowledgement).decode("utf-8")},
        )

    async def receive_failure(self) -> TransportFailure:
        self._require_client()
        if self._failures.empty():
            await self._poll_failures()
        failure = await self._failures.get()
        self._failures.task_done()
        return failure

    async def synchronize_artifacts(
        self,
        receiver: TransportArtifactReceiver,
        *,
        limit: int = 100,
        chunk_size: int = 256 * 1024,
    ) -> ArtifactSyncSummary:
        if chunk_size < 1 or chunk_size > MAX_PROTOCOL_CHUNK_BYTES:
            raise ValueError("chunk_size exceeds BoberAgent protocol bounds")
        result = await self._call_value("boberagent.list_artifacts", {"limit": limit})
        descriptors = tuple(
            ArtifactDescriptor.model_validate_json(item)
            for item in _string_list(result, "Artifact descriptors")
        )
        synchronized = 0
        failed = 0
        for descriptor in descriptors:
            try:
                accepted = await self._synchronize_artifact(
                    receiver, descriptor, chunk_size=chunk_size
                )
            except Exception as error:
                # Node-local SYNC_PENDING state is intentionally retained across carrier loss.
                with suppress(TransportDisconnected):
                    await self._call_value(
                        "boberagent.fail_artifact",
                        {
                            "artifact_ref": str(descriptor.artifact_id),
                            "error": f"{type(error).__name__}: synchronization failed",
                        },
                    )
                failed += 1
                continue
            if accepted:
                synchronized += 1
            else:
                failed += 1
        return ArtifactSyncSummary(
            attempted=len(descriptors), synchronized=synchronized, failed=failed
        )

    async def _synchronize_artifact(
        self,
        receiver: TransportArtifactReceiver,
        descriptor: ArtifactDescriptor,
        *,
        chunk_size: int,
    ) -> bool:
        node_id = self.configuration.node_id
        transfer_id = artifact_transfer_id(node_id, descriptor.artifact_id)
        start = ArtifactTransferStart(
            message_id=artifact_start_message_id(transfer_id),
            node_id=node_id,
            transfer_id=transfer_id,
            timestamp=datetime.now(UTC),
            descriptor=descriptor,
        )
        response = parse_artifact_response(
            await receiver.accept_artifact_message(serialize_message(start))
        )
        if isinstance(response, ArtifactTransferRejection):
            await self._mark_artifact_failed(descriptor, response)
            return False
        if isinstance(response, ArtifactTransferAcknowledgement):
            await self._mark_artifact_complete(descriptor)
            return True
        offset = response.next_offset
        while descriptor.size_bytes is not None and offset < descriptor.size_bytes:
            read = ArtifactReadRequest(
                artifact_ref=descriptor.artifact_id,
                offset=offset,
                max_bytes=chunk_size,
            )
            raw = await self._call_text(
                "boberagent.read_artifact", {"payload": read.model_dump_json()}
            )
            chunk_data = ArtifactReadResponse.model_validate_json(raw)
            if chunk_data.offset != offset or not chunk_data.data:
                raise ProtocolError("MCP Artifact source returned an invalid chunk")
            chunk = ArtifactChunk(
                message_id=artifact_chunk_message_id(transfer_id, offset),
                node_id=node_id,
                transfer_id=transfer_id,
                artifact_ref=descriptor.artifact_id,
                timestamp=datetime.now(UTC),
                offset=offset,
                data=chunk_data.data,
                chunk_sha256=hashlib.sha256(chunk_data.data).hexdigest(),
            )
            response = parse_artifact_response(
                await receiver.accept_artifact_message(serialize_message(chunk))
            )
            if isinstance(response, ArtifactTransferRejection):
                await self._mark_artifact_failed(descriptor, response)
                return False
            if isinstance(response, ArtifactTransferAcknowledgement):
                await self._mark_artifact_complete(descriptor)
                return True
            if not isinstance(response, ArtifactTransferReady) or response.next_offset <= offset:
                raise ProtocolError("Core did not advance the Artifact transfer offset")
            offset = response.next_offset

        finalize = ArtifactTransferFinalize(
            message_id=artifact_finalize_message_id(transfer_id),
            node_id=node_id,
            transfer_id=transfer_id,
            artifact_ref=descriptor.artifact_id,
            timestamp=datetime.now(UTC),
        )
        response = parse_artifact_response(
            await receiver.accept_artifact_message(serialize_message(finalize))
        )
        if isinstance(response, ArtifactTransferAcknowledgement):
            await self._mark_artifact_complete(descriptor)
            return True
        if isinstance(response, ArtifactTransferRejection):
            await self._mark_artifact_failed(descriptor, response)
            return False
        raise ProtocolError("Core did not finalize the Artifact transfer")

    async def _mark_artifact_complete(self, descriptor: ArtifactDescriptor) -> None:
        await self._call_value(
            "boberagent.complete_artifact",
            {"artifact_ref": str(descriptor.artifact_id)},
        )

    async def _mark_artifact_failed(
        self, descriptor: ArtifactDescriptor, rejection: ArtifactTransferRejection
    ) -> None:
        await self._call_value(
            "boberagent.fail_artifact",
            {
                "artifact_ref": str(descriptor.artifact_id),
                "error": f"{rejection.code}: {rejection.message}",
            },
        )

    async def _poll_failures(self) -> None:
        result = await self._call_value(
            "boberagent.poll_failures",
            {"limit": self.configuration.poll_batch_size},
        )
        for item in _string_list(result, "transport failures"):
            failure = TransportFailure.model_validate_json(item)
            try:
                self._failures.put_nowait(failure)
            except asyncio.QueueFull as error:
                raise TransportBackpressure("MCP failure queue is full") from error

    async def _call_text(self, name: str, arguments: dict[str, object]) -> str:
        value = await self._call_value(name, arguments)
        if not isinstance(value, str):
            raise ProtocolError(f"MCP tool {name} returned a non-text payload")
        return value

    async def _call_value(self, name: str, arguments: dict[str, object]) -> object:
        client = self._require_client()
        try:
            result = await client.call_tool(name, arguments)
        except Exception as error:
            await self.disconnect()
            raise TransportDisconnected(
                f"MCP call failed: {type(error).__name__}",
                node_id=self.configuration.node_id,
            ) from error
        return _tool_value(name, result)

    def _validate_target(self, node_id: str) -> None:
        self._require_client()
        if node_id != self.configuration.node_id:
            raise UnknownNode(f"MCP connection does not target Node: {node_id}")

    def _require_client(self) -> Client:
        if not self.connected or self._client is None:
            raise TransportDisconnected(
                "MCP transport is disconnected", node_id=self.configuration.node_id
            )
        return self._client


def _tool_value(name: str, result: CallToolResult) -> object:
    if result.is_error:
        detail = next(
            (item.text for item in result.content if isinstance(item, TextContent)),
            "remote MCP tool error",
        )
        raise ProtocolError(f"MCP tool {name} rejected the request: {detail}")
    if result.structured_content is not None:
        structured = cast(object, result.structured_content)
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    text = next((item.text for item in result.content if isinstance(item, TextContent)), None)
    if text is None:
        raise ProtocolError(f"MCP tool {name} returned no payload")
    try:
        return cast(object, json.loads(text))
    except json.JSONDecodeError:
        return text


def _string_list(value: object, purpose: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProtocolError(f"MCP returned invalid {purpose}")
    return value
