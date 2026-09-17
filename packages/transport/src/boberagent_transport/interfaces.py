"""Async structural interfaces implemented by transport adapters and Node endpoints."""

from typing import Protocol

from .artifact import ArtifactTransferRequest, ArtifactTransferResponse
from .models import (
    DeliveryAcknowledgement,
    InvocationDelivery,
    NodeAdvertisement,
    TransportFailure,
    TransportMessageId,
)


class TransportNodeEndpoint(Protocol):
    @property
    def node_id(self) -> str: ...

    async def handshake(self, request: bytes) -> bytes: ...

    async def accept_invocation(self, message: bytes) -> None: ...

    async def pending_outbound(self) -> tuple[bytes, ...]: ...

    async def acknowledge(self, message: bytes) -> None: ...


class TransportArtifactReceiver(Protocol):
    async def accept_artifact_message(self, message: bytes) -> bytes: ...


class ArtifactTransport(Protocol):
    @property
    def connected(self) -> bool: ...

    async def exchange_artifact(
        self, request: ArtifactTransferRequest
    ) -> ArtifactTransferResponse: ...


class CapabilityTransport(Protocol):
    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def discover_node(self, node_id: str) -> NodeAdvertisement: ...

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId: ...

    async def flush_outboxes(self, node_id: str) -> int: ...

    async def receive(self) -> bytes: ...

    async def acknowledge(self, acknowledgement: DeliveryAcknowledgement) -> None: ...

    async def receive_failure(self) -> TransportFailure: ...
