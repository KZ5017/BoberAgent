"""Milestone 8 Registry/Router integration through real Node handshakes and transport."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from boberagent_contracts import AssetRef, CapabilityInvocation, CapabilityRunRef, MissionRef
from boberagent_core import (
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    ExplicitProviderUnavailable,
    NoEligibleProvider,
    ProviderAvailability,
    upgrade_database,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
    ToolConfiguration,
)
from boberagent_transport import (
    AssetProjection,
    InMemoryTransport,
    InvocationDelivery,
    MissionProjection,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_ROOT = REPOSITORY_ROOT / "capabilities" / "network-service-discovery"
SHIM_FIXTURE = CAPABILITY_ROOT / "tests" / "fixtures" / "nmap_shim.py"
MISSION_REF = MissionRef("mission-routed-discovery")
ASSET_REF = AssetRef("asset-routed-discovery")
ADDRESS = "192.0.2.25"


def _make_nmap_shim(tmp_path: Path) -> Path:
    target = tmp_path / "nmap-router-shim"
    source_lines = SHIM_FIXTURE.read_text(encoding="utf-8").splitlines()
    source_lines[0] = f"#!{sys.executable}"
    target.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    target.chmod(0o700)
    return target


def _configuration(
    root: Path,
    *,
    node_id: str,
    nmap_executable: Path | None,
) -> NodeConfiguration:
    tools = (
        {}
        if nmap_executable is None
        else {"nmap": ToolConfiguration(executable=str(nmap_executable))}
    )
    return NodeConfiguration.for_runtime_directory(
        root,
        capability_paths=(CAPABILITY_ROOT,),
        tools=tools,
        configured_node_id=node_id,
    )


def _delivery(run_id: str) -> InvocationDelivery:
    invocation = CapabilityInvocation(
        run_id=CapabilityRunRef(run_id),
        capability_id="network.service_discovery",
        operation="discover",
        mission_ref=MISSION_REF,
        inputs={
            "asset_ref": str(ASSET_REF),
            "profile": "quick",
            "timeout_seconds": 10,
        },
    )
    return InvocationDelivery(
        invocation=invocation,
        mission=MissionProjection(mission_ref=MISSION_REF, name="Routed discovery"),
        allowed_assets=(ASSET_REF,),
        allowed_addresses=(ADDRESS,),
        assets=(AssetProjection(asset_ref=ASSET_REF, primary_address=ADDRESS),),
    )


def test_handshake_registry_router_dispatch_and_result_delivery_with_two_nodes(
    tmp_path: Path,
) -> None:
    shim = _make_nmap_shim(tmp_path)
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    registry = CapabilityRegistry(database)
    transport = InMemoryTransport(queue_capacity=30)
    registration = CapabilityRegistrationClient(transport, registry)
    receiver = CoreTransportReceiver(database)
    receiver_client = CoreTransportClient(transport, receiver)
    router = CapabilityRouter(registry, transport)

    async def scenario() -> None:
        first = ExecutionNode(
            _configuration(
                tmp_path / "node-a",
                node_id="node-routing-a",
                nmap_executable=shim,
            )
        )
        second = ExecutionNode(
            _configuration(
                tmp_path / "node-b",
                node_id="node-routing-b",
                nmap_executable=shim,
            )
        )
        await first.initialize()
        await second.initialize()
        first_endpoint = ExecutionNodeTransportEndpoint(first)
        second_endpoint = ExecutionNodeTransportEndpoint(second)
        transport.register_node(first_endpoint)
        transport.register_node(second_endpoint)
        await transport.connect()

        await registration.refresh_node(first_endpoint.node_id)
        await registration.refresh_node(second_endpoint.node_id)
        providers = registry.list_providers("network.service_discovery")
        assert len(providers) == 2
        assert all(
            provider.availability is ProviderAvailability.AVAILABLE for provider in providers
        )

        selected = router.select_provider(
            capability_id="network.service_discovery", operation="discover"
        )
        assert selected.provider_id == min(
            (provider.provider_id for provider in providers), key=lambda value: str(value)
        )
        other = next(provider for provider in providers if provider != selected)
        assert (
            router.select_provider(
                capability_id="network.service_discovery",
                operation="discover",
                node_id=other.node_id,
            )
            == other
        )

        registration.mark_node_disconnected(other.node_id)
        with pytest.raises(ExplicitProviderUnavailable):
            router.select_provider(
                capability_id="network.service_discovery",
                operation="discover",
                node_id=other.node_id,
            )
        await registration.refresh_node(other.node_id)

        delivery = _delivery("run-routed-service-discovery")
        routed = router.select_provider(
            capability_id=delivery.invocation.capability_id,
            operation=delivery.invocation.operation,
        )
        await router.dispatch(
            invocation=delivery.invocation,
            delivery=delivery,
            provider=routed,
        )
        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)

        selected_node = first if routed.node_id == first_endpoint.node_id else second
        unselected_node = second if selected_node is first else first
        assert selected_node.store is not None
        assert selected_node.store.get_run(delivery.invocation.run_id) is not None
        assert unselected_node.store is not None
        assert unselected_node.store.get_run(delivery.invocation.run_id) is None

        count = await receiver_client.flush_node(routed.node_id)
        assert count > 0
        for _ in range(count):
            await receiver_client.receive_one()
        result = receiver.result_for_run(delivery.invocation.run_id)
        assert result is not None
        assert result.result.run_ref == delivery.invocation.run_id
        assert result.result.observations
        decision = registry.routing_decision_for_run(delivery.invocation.run_id)
        assert decision is not None
        assert decision.provider_id == routed.provider_id
        with database.unit_of_work() as work:
            assert work.observations.get(result.result.observations[0].observation_id) is None

        await transport.disconnect()
        await first.shutdown()
        await second.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_node_handshake_advertises_missing_dependency_as_unavailable(tmp_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    registry = CapabilityRegistry(database)
    transport = InMemoryTransport()
    registration = CapabilityRegistrationClient(transport, registry)
    router = CapabilityRouter(registry, transport)

    async def scenario() -> None:
        node = ExecutionNode(
            _configuration(
                tmp_path / "node-missing",
                node_id="node-routing-missing",
                nmap_executable=None,
            )
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport.register_node(endpoint)
        await transport.connect()

        advertisement, providers = await registration.refresh_node(endpoint.node_id)
        assert advertisement.capabilities[0].capability_id == "network.service_discovery"
        assert providers[0].availability is ProviderAvailability.UNAVAILABLE
        assert "dependencies" in (providers[0].unavailability_reason or "")
        with pytest.raises(NoEligibleProvider):
            router.select_provider(capability_id="network.service_discovery", operation="discover")

        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
