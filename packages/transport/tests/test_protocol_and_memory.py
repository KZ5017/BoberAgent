"""Transport envelope serialization, connection, and backpressure tests."""

import asyncio
from datetime import UTC, datetime

import pytest
from boberagent_contracts import (
    AssetRef,
    CapabilityInvocation,
    CapabilityRunRef,
    MissionRef,
)
from boberagent_transport import (
    AssetProjection,
    InMemoryTransport,
    InvocationDelivery,
    InvocationEnvelope,
    MissionProjection,
    TransportBackpressure,
    TransportDisconnected,
    UnknownNode,
    invocation_fingerprint,
    invocation_message_id,
    parse_invocation,
    serialize_message,
)


def _delivery(run_ref: str = "run-transport-unit") -> InvocationDelivery:
    mission_ref = MissionRef("mission-transport-unit")
    asset_ref = AssetRef("asset-transport-unit")
    return InvocationDelivery(
        invocation=CapabilityInvocation(
            run_id=CapabilityRunRef(run_ref),
            capability_id="test.transport_unit",
            operation="execute",
            mission_ref=mission_ref,
            inputs={"asset_ref": str(asset_ref)},
        ),
        mission=MissionProjection(mission_ref=mission_ref),
        allowed_assets=(asset_ref,),
        assets=(AssetProjection(asset_ref=asset_ref, primary_address="192.0.2.10"),),
    )


def test_invocation_envelope_json_round_trip_and_stable_fingerprint() -> None:
    delivery = _delivery()
    envelope = InvocationEnvelope(
        message_id=invocation_message_id(delivery.invocation.run_id),
        node_id="node-unit",
        correlation_id=delivery.invocation.run_id,
        timestamp=datetime(2026, 9, 17, tzinfo=UTC),
        delivery=delivery,
    )

    restored = parse_invocation(serialize_message(envelope))
    reordered = InvocationDelivery.model_validate_json(delivery.model_dump_json())

    assert restored == envelope
    assert invocation_fingerprint(reordered) == invocation_fingerprint(delivery)


class BlockingEndpoint:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def node_id(self) -> str:
        return "node-blocking"

    async def handshake(self, request: bytes) -> bytes:
        return request

    async def accept_invocation(self, message: bytes) -> None:
        del message
        self.started.set()
        await self.release.wait()

    async def pending_outbound(self) -> tuple[bytes, ...]:
        return ()

    async def acknowledge(self, message: bytes) -> None:
        del message


def test_in_memory_transport_is_bounded_and_connection_explicit() -> None:
    async def scenario() -> None:
        endpoint = BlockingEndpoint()
        transport = InMemoryTransport(queue_capacity=1, max_in_flight=1)
        transport.register_node(endpoint)

        with pytest.raises(TransportDisconnected):
            await transport.submit_invocation(endpoint.node_id, _delivery("run-disconnected"))

        await transport.connect()
        with pytest.raises(UnknownNode):
            await transport.submit_invocation("node-unknown", _delivery("run-unknown"))

        await transport.submit_invocation(endpoint.node_id, _delivery("run-first"))
        await asyncio.wait_for(endpoint.started.wait(), timeout=2)
        await transport.submit_invocation(endpoint.node_id, _delivery("run-second"))
        with pytest.raises(TransportBackpressure):
            await transport.submit_invocation(endpoint.node_id, _delivery("run-third"))

        endpoint.release.set()
        await asyncio.wait_for(transport.wait_for_idle(), timeout=2)
        await transport.disconnect()

    asyncio.run(scenario())
