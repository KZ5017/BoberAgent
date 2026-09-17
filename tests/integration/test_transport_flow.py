"""Milestone 5 Core-to-Node protocol integration without network transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from boberagent_contracts import (
    AssetRef,
    CapabilityInvocation,
    CapabilityRunRef,
    MissionRef,
)
from boberagent_core import (
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    upgrade_database,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
    NodeLifecycleState,
)
from boberagent_transport import (
    AssetProjection,
    DeliveryKind,
    InMemoryTransport,
    InvocationDelivery,
    InvocationEnvelope,
    MissionProjection,
    TransportDisconnected,
    UnknownNode,
    invocation_message_id,
    serialize_message,
)
from transport_test_capability import (
    TransportSyntheticCapability,
    allow_completion,
    capability_manifest,
    execution_started,
    reset_control,
)

MISSION_REF = MissionRef("mission-transport-integration")
ASSET_REF = AssetRef("asset-transport-integration")


def _write_manifest(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "capability.json").write_text(
        json.dumps(capability_manifest(), indent=2), encoding="utf-8"
    )


def _node_configuration(tmp_path: Path) -> NodeConfiguration:
    capability_path = tmp_path / "capabilities"
    _write_manifest(capability_path)
    return NodeConfiguration.for_runtime_directory(
        tmp_path / "node-runtime",
        capability_paths=(capability_path,),
        configured_node_id="node-transport-test",
    )


def _delivery(
    run_ref: str,
    *,
    message: str = "serialized transport payload",
    wait_for_release: bool = False,
) -> InvocationDelivery:
    invocation = CapabilityInvocation(
        run_id=CapabilityRunRef(run_ref),
        capability_id="test.transport_synthetic",
        operation="execute",
        mission_ref=MISSION_REF,
        inputs={
            "asset_ref": str(ASSET_REF),
            "message": message,
            "wait_for_release": wait_for_release,
        },
    )
    return InvocationDelivery(
        invocation=invocation,
        mission=MissionProjection(mission_ref=MISSION_REF, name="Transport tests"),
        allowed_assets=(ASSET_REF,),
        allowed_addresses=("192.0.2.80",),
        assets=(
            AssetProjection(
                asset_ref=ASSET_REF,
                primary_address="192.0.2.80",
            ),
        ),
    )


def _core_database(path: Path) -> CoreDatabase:
    database = CoreDatabase(DatabaseConfig.sqlite(path))
    upgrade_database(database)
    return database


def test_end_to_end_outbox_delivery_lost_ack_and_core_restart(tmp_path: Path) -> None:
    reset_control()
    configuration = _node_configuration(tmp_path)
    core_path = tmp_path / "core.sqlite3"
    database = _core_database(core_path)
    delivery = _delivery("run-transport-e2e")

    async def scenario() -> tuple[bytes, str]:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport(queue_capacity=20)
        transport.register_node(endpoint)
        receiver = CoreTransportReceiver(database)
        client = CoreTransportClient(transport, receiver)
        await transport.connect()

        advertisement = await client.discover_node(endpoint.node_id)
        assert advertisement.node_id == endpoint.node_id
        assert advertisement.lifecycle == NodeLifecycleState.READY.value
        assert [definition.capability_id for definition in advertisement.capabilities] == [
            "test.transport_synthetic"
        ]

        await client.submit_invocation(endpoint.node_id, delivery)
        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
        assert TransportSyntheticCapability.execution_count == 1
        assert node.store is not None
        assert len(node.store.pending_events()) == 3
        assert len(node.store.pending_results()) == 1

        assert await client.flush_node(endpoint.node_id) == 4
        lost_kinds: set[DeliveryKind] = set()
        lost_result_bytes = b""
        lost_result_id = ""
        for _ in range(4):
            serialized = await asyncio.wait_for(transport.receive(), timeout=2)
            record, acknowledgement = receiver.accept(serialized)
            if record.message_kind not in lost_kinds:
                lost_kinds.add(record.message_kind)
                if record.message_kind is DeliveryKind.RESULT:
                    lost_result_bytes = serialized
                    lost_result_id = str(record.message_id)
            else:
                await transport.acknowledge(acknowledgement)
        assert lost_kinds == {DeliveryKind.EVENT, DeliveryKind.RESULT}
        assert len(node.store.pending_events()) == 1
        assert len(node.store.pending_results()) == 1

        assert await client.flush_node(endpoint.node_id) == 2
        for _ in range(2):
            await client.receive_one(acknowledge=True)
        assert not node.store.pending_events()
        assert not node.store.pending_results()

        records = receiver.records_for_run(delivery.invocation.run_id)
        assert len(records) == 4
        assert sorted(record.delivery_count for record in records) == [1, 1, 2, 2]
        events = receiver.events_for_run(delivery.invocation.run_id)
        result = receiver.result_for_run(delivery.invocation.run_id)
        assert len(events) == 3
        assert result is not None
        observation_value = result.result.observations[0].value
        assert isinstance(observation_value, dict)
        assert observation_value["message"] == "serialized transport payload"
        artifact_ref = result.result.artifacts[0].artifact_id
        observation_ref = result.result.observations[0].observation_id
        with database.unit_of_work() as work:
            assert work.artifacts.get(artifact_ref) is None
            assert work.observations.get(observation_ref) is None

        await transport.disconnect()
        await node.shutdown()
        return lost_result_bytes, lost_result_id

    lost_result_bytes, lost_result_id = asyncio.run(scenario())
    database.dispose()

    reopened = _core_database(core_path)
    try:
        restarted_receiver = CoreTransportReceiver(reopened)
        duplicate, _acknowledgement = restarted_receiver.accept(lost_result_bytes)
        assert str(duplicate.message_id) == lost_result_id
        assert duplicate.delivery_count == 3
        assert len(restarted_receiver.records_for_run(delivery.invocation.run_id)) == 4
    finally:
        reopened.dispose()


def test_duplicate_and_conflicting_invocations(tmp_path: Path) -> None:
    reset_control()
    configuration = _node_configuration(tmp_path)
    database = _core_database(tmp_path / "core.sqlite3")
    original = _delivery("run-transport-duplicate")

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)
        client = CoreTransportClient(transport, CoreTransportReceiver(database))
        await transport.connect()

        await client.submit_invocation(endpoint.node_id, original)
        await client.submit_invocation(endpoint.node_id, original)
        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
        assert TransportSyntheticCapability.execution_count == 1
        assert node.store is not None
        assert len(node.store.list_workspaces_for_owner(str(original.invocation.run_id))) == 1
        assert len(node.store.pending_results()) == 1

        conflicting = _delivery("run-transport-duplicate", message="materially different payload")
        await client.submit_invocation(endpoint.node_id, conflicting)
        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
        failure = await asyncio.wait_for(transport.receive_failure(), timeout=2)
        assert failure.code == "CONFLICTING_INVOCATION"
        assert failure.correlation_id == original.invocation.run_id
        assert TransportSyntheticCapability.execution_count == 1

        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_disconnect_does_not_cancel_node_and_reconnect_delivers(tmp_path: Path) -> None:
    reset_control()
    configuration = _node_configuration(tmp_path)
    database = _core_database(tmp_path / "core.sqlite3")
    delivery = _delivery("run-transport-disconnect", wait_for_release=True)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)
        client = CoreTransportClient(transport, CoreTransportReceiver(database))
        await transport.connect()
        await client.submit_invocation(endpoint.node_id, delivery)
        await asyncio.wait_for(execution_started.wait(), timeout=2)

        await transport.disconnect()
        allow_completion.set()
        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
        assert node.lifecycle.state is NodeLifecycleState.READY
        assert node.store is not None
        assert len(node.store.pending_results()) == 1
        with pytest.raises(TransportDisconnected):
            await client.flush_node(endpoint.node_id)

        await transport.connect()
        count = await client.flush_node(endpoint.node_id)
        assert count == 4
        for _ in range(count):
            await client.receive_one()
        assert not node.store.pending_events()
        assert not node.store.pending_results()
        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_protocol_corruption_unknown_node_and_unsupported_version(tmp_path: Path) -> None:
    reset_control()
    configuration = _node_configuration(tmp_path)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)

        with pytest.raises(TransportDisconnected):
            await transport.discover_node(endpoint.node_id)
        await transport.connect()
        with pytest.raises(UnknownNode):
            await transport.discover_node("node-does-not-exist")

        await transport.send_serialized_invocation(endpoint.node_id, b"{not-json")
        await asyncio.wait_for(transport.wait_for_idle(), timeout=2)
        malformed = await asyncio.wait_for(transport.receive_failure(), timeout=2)
        assert malformed.code == "MALFORMED_MESSAGE"

        delivery = _delivery("run-unsupported-protocol")
        unsupported = InvocationEnvelope(
            protocol_version="99.0",
            message_id=invocation_message_id(delivery.invocation.run_id),
            node_id=endpoint.node_id,
            correlation_id=delivery.invocation.run_id,
            timestamp=node.health().checked_at,
            delivery=delivery,
        )
        await transport.send_serialized_invocation(endpoint.node_id, serialize_message(unsupported))
        await asyncio.wait_for(transport.wait_for_idle(), timeout=2)
        failure = await asyncio.wait_for(transport.receive_failure(), timeout=2)
        assert failure.code == "UNSUPPORTED_PROTOCOL_VERSION"
        assert node.store is not None
        assert node.store.get_run(delivery.invocation.run_id) is None

        await transport.disconnect()
        await node.shutdown()

    asyncio.run(scenario())


def test_pending_result_survives_node_restart_and_delivers(tmp_path: Path) -> None:
    reset_control()
    configuration = _node_configuration(tmp_path)
    database = _core_database(tmp_path / "core.sqlite3")
    delivery = _delivery("run-transport-node-restart")

    async def scenario() -> None:
        first_node = ExecutionNode(configuration)
        await first_node.initialize()
        first_endpoint = ExecutionNodeTransportEndpoint(first_node)
        transport = InMemoryTransport()
        transport.register_node(first_endpoint)
        client = CoreTransportClient(transport, CoreTransportReceiver(database))
        await transport.connect()
        await client.submit_invocation(first_endpoint.node_id, delivery)
        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
        assert TransportSyntheticCapability.execution_count == 1
        await transport.disconnect()
        await first_node.shutdown()

        restarted_node = ExecutionNode(configuration)
        await restarted_node.initialize()
        restarted_endpoint = ExecutionNodeTransportEndpoint(restarted_node)
        transport.register_node(restarted_endpoint, replace=True)
        await transport.connect()
        advertisement = await client.discover_node(restarted_endpoint.node_id)
        assert advertisement.node_id == first_endpoint.node_id
        count = await client.flush_node(restarted_endpoint.node_id)
        assert count == 4
        for _ in range(count):
            await client.receive_one()
        assert restarted_node.store is not None
        assert not restarted_node.store.pending_results()

        await client.submit_invocation(restarted_endpoint.node_id, delivery)
        await asyncio.wait_for(transport.wait_for_idle(), timeout=2)
        assert TransportSyntheticCapability.execution_count == 1
        assert not restarted_node.store.pending_results()
        await transport.disconnect()
        await restarted_node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
