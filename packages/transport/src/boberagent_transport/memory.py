"""Bounded, reconnectable, serialization-faithful in-memory transport."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import uuid4

from boberagent_contracts import CapabilityRunRef, CapabilityRunStatus

from .artifact import (
    ArtifactTransferRequest,
    ArtifactTransferResponse,
    ArtifactTransferStart,
    parse_artifact_response,
)
from .errors import (
    ArtifactTransferUnavailable,
    ProtocolError,
    TransportBackpressure,
    TransportDisconnected,
    TransportError,
    UnknownNode,
)
from .interfaces import TransportArtifactReceiver, TransportNodeEndpoint
from .models import (
    DeliveryAcknowledgement,
    HandshakeRequest,
    InvocationDelivery,
    InvocationEnvelope,
    NodeAdvertisement,
    RunStatusRequest,
    TransportFailure,
    TransportMessageId,
    ensure_supported_protocol,
    invocation_message_id,
    parse_advertisement,
    parse_outbound,
    parse_run_status_response,
    serialize_message,
)


class InMemoryTransport:
    """A protocol adapter, not a shortcut around serialized transport envelopes."""

    def __init__(self, *, queue_capacity: int = 100, max_in_flight: int = 10) -> None:
        if queue_capacity < 1 or max_in_flight < 1:
            raise ValueError("queue_capacity and max_in_flight must be positive")
        self._endpoints: dict[str, TransportNodeEndpoint] = {}
        self._artifact_receiver: TransportArtifactReceiver | None = None
        self._inbound: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(queue_capacity)
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue(queue_capacity)
        self._failures: asyncio.Queue[TransportFailure] = asyncio.Queue(queue_capacity)
        self._queued_outbound_ids: set[str] = set()
        self._in_flight = asyncio.Semaphore(max_in_flight)
        self._connected = False
        self._worker: asyncio.Task[None] | None = None
        self._node_tasks: set[asyncio.Task[None]] = set()

    @property
    def connected(self) -> bool:
        return self._connected

    def register_node(self, endpoint: TransportNodeEndpoint, *, replace: bool = False) -> None:
        existing = self._endpoints.get(endpoint.node_id)
        if existing is not None and existing is not endpoint and not replace:
            raise ValueError(f"Node is already registered: {endpoint.node_id}")
        self._endpoints[endpoint.node_id] = endpoint

    def register_artifact_receiver(self, receiver: TransportArtifactReceiver) -> None:
        self._artifact_receiver = receiver

    async def connect(self) -> None:
        if self._connected:
            return
        self._connected = True
        self._worker = asyncio.create_task(self._run_inbound())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def discover_node(self, node_id: str) -> NodeAdvertisement:
        self._require_connected()
        endpoint = self._endpoint(node_id)
        request = HandshakeRequest(
            message_id=TransportMessageId(f"transport-handshake:{uuid4()}"),
            node_id=node_id,
            timestamp=datetime.now(UTC),
        )
        advertisement = parse_advertisement(await endpoint.handshake(serialize_message(request)))
        ensure_supported_protocol(advertisement.protocol_version)
        if advertisement.node_id != node_id:
            raise UnknownNode("handshake returned a different Node identity", node_id=node_id)
        return advertisement

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId:
        envelope = InvocationEnvelope(
            message_id=invocation_message_id(delivery.invocation.run_id),
            node_id=node_id,
            correlation_id=delivery.invocation.run_id,
            timestamp=datetime.now(UTC),
            delivery=delivery,
        )
        await self.send_serialized_invocation(node_id, serialize_message(envelope))
        return envelope.message_id

    async def send_serialized_invocation(self, node_id: str, message: bytes) -> None:
        self._require_connected()
        self._endpoint(node_id)
        try:
            self._inbound.put_nowait((node_id, bytes(message)))
        except asyncio.QueueFull as error:
            raise TransportBackpressure("inbound transport queue is full") from error

    async def query_run_status(
        self, node_id: str, run_ref: CapabilityRunRef
    ) -> CapabilityRunStatus | None:
        self._require_connected()
        endpoint = self._endpoint(node_id)
        request = RunStatusRequest(
            message_id=TransportMessageId(f"transport-run-status:{uuid4()}"),
            node_id=node_id,
            correlation_id=run_ref,
            timestamp=datetime.now(UTC),
        )
        response = parse_run_status_response(
            await endpoint.query_run_status(serialize_message(request))
        )
        if (
            response.request_message_id != request.message_id
            or response.node_id != node_id
            or response.correlation_id != run_ref
        ):
            raise ProtocolError("Run status response does not match its request")
        return response.status

    async def flush_outboxes(self, node_id: str) -> int:
        self._require_connected()
        endpoint = self._endpoint(node_id)
        queued = 0
        for serialized in await endpoint.pending_outbound():
            envelope = parse_outbound(serialized)
            if envelope.node_id != node_id:
                raise ProtocolError(
                    "outbound envelope identifies a different Node",
                    node_id=node_id,
                    message_id=str(envelope.message_id),
                    correlation_id=envelope.correlation_id,
                )
            identity = str(envelope.message_id)
            if identity in self._queued_outbound_ids:
                continue
            try:
                self._outbound.put_nowait(serialized)
            except asyncio.QueueFull:
                break
            self._queued_outbound_ids.add(identity)
            queued += 1
        return queued

    async def receive(self) -> bytes:
        self._require_connected()
        message = await self._outbound.get()
        envelope = parse_outbound(message)
        self._queued_outbound_ids.discard(str(envelope.message_id))
        self._outbound.task_done()
        return message

    async def acknowledge(self, acknowledgement: DeliveryAcknowledgement) -> None:
        self._require_connected()
        endpoint = self._endpoint(acknowledgement.node_id)
        await endpoint.acknowledge(serialize_message(acknowledgement))

    async def exchange_artifact(self, request: ArtifactTransferRequest) -> ArtifactTransferResponse:
        self._require_connected()
        self._endpoint(request.node_id)
        receiver = self._artifact_receiver
        if receiver is None:
            raise ArtifactTransferUnavailable("no Core Artifact receiver is registered")
        serialized = await receiver.accept_artifact_message(serialize_message(request))
        response = parse_artifact_response(serialized)
        ensure_supported_protocol(response.protocol_version)
        if (
            response.request_message_id != request.message_id
            or response.node_id != request.node_id
            or response.transfer_id != request.transfer_id
        ):
            raise ProtocolError("Artifact transfer response does not match its request")
        artifact_ref = (
            request.descriptor.artifact_id
            if isinstance(request, ArtifactTransferStart)
            else request.artifact_ref
        )
        if response.artifact_ref != artifact_ref:
            raise ProtocolError("Artifact transfer response identifies a different Artifact")
        return response

    async def receive_failure(self) -> TransportFailure:
        self._require_connected()
        failure = await self._failures.get()
        self._failures.task_done()
        return failure

    async def wait_for_idle(self) -> None:
        """Development helper; canonical result delivery still uses the outbound queue."""

        await self._inbound.join()
        if self._node_tasks:
            await asyncio.gather(*tuple(self._node_tasks))

    async def _run_inbound(self) -> None:
        while True:
            await self._in_flight.acquire()
            try:
                node_id, message = await self._inbound.get()
            except BaseException:
                self._in_flight.release()
                raise
            task = asyncio.create_task(self._deliver(node_id, message))
            self._node_tasks.add(task)
            task.add_done_callback(self._node_tasks.discard)

    async def _deliver(self, node_id: str, message: bytes) -> None:
        try:
            await self._endpoint(node_id).accept_invocation(message)
        except TransportError as error:
            await self._failures.put(
                TransportFailure(
                    code=error.code,
                    message=str(error),
                    node_id=error.node_id or node_id,
                    message_id=error.message_id,
                    correlation_id=error.correlation_id,
                )
            )
        except Exception as error:
            await self._failures.put(
                TransportFailure(
                    code="ENDPOINT_FAILURE",
                    message=f"Node endpoint failed: {type(error).__name__}",
                    node_id=node_id,
                )
            )
        finally:
            self._inbound.task_done()
            self._in_flight.release()

    def _endpoint(self, node_id: str) -> TransportNodeEndpoint:
        try:
            return self._endpoints[node_id]
        except KeyError as error:
            raise UnknownNode(f"Node is not registered: {node_id}", node_id=node_id) from error

    def _require_connected(self) -> None:
        if not self._connected:
            raise TransportDisconnected("in-memory transport is disconnected")
