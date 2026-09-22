"""Async structural interfaces implemented by transport adapters and Node endpoints."""

from typing import Protocol

from boberagent_contracts import CapabilityRunRef, CapabilityRunStatus, InteractionResponse

from .artifact import ArtifactTransferRequest, ArtifactTransferResponse
from .models import (
    DeliveryAcknowledgement,
    InteractionResponseAcknowledgement,
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

    async def query_run_status(self, message: bytes) -> bytes: ...

    async def pending_outbound(self) -> tuple[bytes, ...]: ...

    async def acknowledge(self, message: bytes) -> None: ...


class TransportArtifactReceiver(Protocol):
    async def accept_artifact_message(self, message: bytes) -> bytes: ...


class TransportInteractionEndpoint(Protocol):
    async def accept_interaction_response(self, message: bytes) -> bytes: ...


class ArtifactTransport(Protocol):
    @property
    def connected(self) -> bool: ...

    async def exchange_artifact(
        self, request: ArtifactTransferRequest
    ) -> ArtifactTransferResponse: ...


class InteractionTransport(Protocol):
    async def submit_interaction_response(
        self, node_id: str, response: InteractionResponse
    ) -> InteractionResponseAcknowledgement: ...


class CapabilityTransport(Protocol):
    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def discover_node(self, node_id: str) -> NodeAdvertisement: ...

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId: ...

    async def query_run_status(
        self, node_id: str, run_ref: CapabilityRunRef
    ) -> CapabilityRunStatus | None: ...

    async def flush_outboxes(self, node_id: str) -> int: ...

    async def receive(self) -> bytes: ...

    async def acknowledge(self, acknowledgement: DeliveryAcknowledgement) -> None: ...

    async def receive_failure(self) -> TransportFailure: ...
