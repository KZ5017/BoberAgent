"""Deterministic provider routing, constraints, dispatch, and provenance tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from boberagent_contracts import CapabilityInvocation, CapabilityRunRef, MissionRef
from boberagent_core import (
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    DatabaseConfig,
    ExplicitProviderUnavailable,
    NoEligibleProvider,
    ProviderAvailability,
    UnknownCapability,
    UnsupportedOperation,
    upgrade_database,
)
from boberagent_transport import (
    CapabilityTransport,
    DeliveryAcknowledgement,
    InvocationDelivery,
    MissionProjection,
    NodeAdvertisement,
    TransportDisconnected,
    TransportFailure,
    TransportMessageId,
    invocation_message_id,
)
from test_capability_registry import MutableClock, advertisement

MISSION_REF = MissionRef("mission-router-test")


class RecordingTransport(CapabilityTransport):
    def __init__(self) -> None:
        self._connected = True
        self.advertisements: dict[str, NodeAdvertisement] = {}
        self.submissions: list[tuple[str, InvocationDelivery]] = []

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def discover_node(self, node_id: str) -> NodeAdvertisement:
        return self.advertisements[node_id]

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId:
        self.submissions.append((node_id, delivery))
        return invocation_message_id(delivery.invocation.run_id)

    async def flush_outboxes(self, node_id: str) -> int:
        del node_id
        return 0

    async def receive(self) -> bytes:
        raise RuntimeError("RecordingTransport has no outbound messages")

    async def acknowledge(self, acknowledgement: DeliveryAcknowledgement) -> None:
        del acknowledgement

    async def receive_failure(self) -> TransportFailure:
        raise RuntimeError("RecordingTransport has no failures")


class RejectingTransport(RecordingTransport):
    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId:
        self.submissions.append((node_id, delivery))
        raise TransportDisconnected("controlled dispatch failure")


def _delivery(run_id: str = "run-router-test") -> InvocationDelivery:
    invocation = CapabilityInvocation(
        run_id=CapabilityRunRef(run_id),
        capability_id="test.registry_capability",
        operation="discover",
        mission_ref=MISSION_REF,
        inputs={},
    )
    return InvocationDelivery(
        invocation=invocation,
        mission=MissionProjection(mission_ref=MISSION_REF),
    )


def test_router_selects_deterministically_and_honors_explicit_constraints(
    database: CoreDatabase,
) -> None:
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
    registry = CapabilityRegistry(database, clock=clock)
    first = registry.register_or_refresh_node(advertisement("node-router-b"))[0]
    second = registry.register_or_refresh_node(advertisement("node-router-a"))[0]
    transport = RecordingTransport()
    router = CapabilityRouter(registry, transport, clock=clock)

    selected = router.select_provider(
        capability_id="test.registry_capability", operation="discover"
    )
    assert selected.provider_id == min(
        (first.provider_id, second.provider_id), key=lambda provider_id: str(provider_id)
    )
    assert (
        router.select_provider(
            capability_id="test.registry_capability",
            operation="discover",
            node_id=first.node_id,
        ).provider_id
        == first.provider_id
    )
    assert (
        router.select_provider(
            capability_id="test.registry_capability",
            operation="discover",
            provider_id=second.provider_id,
        ).provider_id
        == second.provider_id
    )

    registry.mark_node_stale(first.node_id)
    remaining = router.select_provider(
        capability_id="test.registry_capability", operation="discover"
    )
    assert remaining.provider_id == second.provider_id
    with pytest.raises(ExplicitProviderUnavailable, match="not available"):
        router.select_provider(
            capability_id="test.registry_capability",
            operation="discover",
            node_id=first.node_id,
        )


def test_router_reports_unknown_unsupported_and_unavailable(database: CoreDatabase) -> None:
    registry = CapabilityRegistry(database)
    router = CapabilityRouter(registry, RecordingTransport())

    with pytest.raises(UnknownCapability):
        router.select_provider(capability_id="unknown.capability", operation="discover")

    provider = registry.register_or_refresh_node(advertisement("node-errors"))[0]
    with pytest.raises(UnsupportedOperation):
        router.select_provider(capability_id="test.registry_capability", operation="unsupported")

    registry.mark_node_stale(provider.node_id)
    stale = registry.get_provider(provider.provider_id)
    assert stale is not None and stale.availability is ProviderAvailability.STALE
    with pytest.raises(NoEligibleProvider):
        router.select_provider(capability_id="test.registry_capability", operation="discover")
    registry.register_or_refresh_node(advertisement("node-errors", lifecycle="OFFLINE"))
    with pytest.raises(NoEligibleProvider):
        router.select_provider(capability_id="test.registry_capability", operation="discover")
    with pytest.raises(ExplicitProviderUnavailable):
        router.select_provider(
            capability_id="test.registry_capability",
            operation="discover",
            provider_id=UUID("00000000-0000-0000-0000-000000000001"),
        )


def test_dispatch_preserves_run_identity_and_persists_decision_across_restart(
    database_path: Path,
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
    registry = CapabilityRegistry(database, clock=clock)
    provider = registry.register_or_refresh_node(advertisement("node-dispatch"))[0]
    transport = RecordingTransport()
    router = CapabilityRouter(registry, transport, clock=clock)
    delivery = _delivery("run-routing-provenance")

    async def dispatch() -> None:
        selected = router.select_provider(
            capability_id=delivery.invocation.capability_id,
            operation=delivery.invocation.operation,
        )
        message_id = await router.dispatch(
            invocation=delivery.invocation,
            delivery=delivery,
            provider=selected,
        )
        assert message_id == invocation_message_id(delivery.invocation.run_id)

    asyncio.run(dispatch())
    assert transport.submissions == [(provider.node_id, delivery)]
    decision = registry.routing_decision_for_run(delivery.invocation.run_id)
    assert decision is not None
    assert decision.run_ref == delivery.invocation.run_id
    assert decision.provider_id == provider.provider_id
    assert decision.implementation_version == provider.implementation_version
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(reopened)
    try:
        restarted = CapabilityRegistry(reopened, clock=clock)
        persisted_provider = restarted.get_provider(provider.provider_id)
        assert persisted_provider is not None
        assert persisted_provider.availability is ProviderAvailability.STALE
        assert restarted.routing_decision_for_run(delivery.invocation.run_id) == decision
    finally:
        reopened.dispose()


def test_transport_failure_records_selection_without_hidden_reroute(
    database: CoreDatabase,
) -> None:
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
    registry = CapabilityRegistry(database, clock=clock)
    registry.register_or_refresh_node(advertisement("node-no-retry-a"))
    registry.register_or_refresh_node(advertisement("node-no-retry-b"))
    transport = RejectingTransport()
    router = CapabilityRouter(registry, transport, clock=clock)
    delivery = _delivery("run-no-hidden-reroute")
    provider = router.select_provider(
        capability_id=delivery.invocation.capability_id,
        operation=delivery.invocation.operation,
    )

    async def dispatch() -> None:
        with pytest.raises(TransportDisconnected):
            await router.dispatch(
                invocation=delivery.invocation,
                delivery=delivery,
                provider=provider,
            )

    asyncio.run(dispatch())
    assert transport.submissions == [(provider.node_id, delivery)]
    decision = registry.routing_decision_for_run(delivery.invocation.run_id)
    assert decision is not None and decision.provider_id == provider.provider_id
