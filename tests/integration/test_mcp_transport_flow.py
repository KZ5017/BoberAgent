"""Milestone 10 real MCP loopback vertical slice."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import ArtifactRef, CapabilityRun, CapabilityRunStatus
from boberagent_core import (
    ArtifactStorageConfiguration,
    Asset,
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
    Mission,
    ResultIngestionService,
    upgrade_database,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
    NodeLifecycleState,
)
from boberagent_execution_node.persistence import ArtifactSyncState
from boberagent_execution_node.transport import NodeMcpArtifactSource
from boberagent_transport import (
    ArtifactChunk,
    ArtifactTransferFinalize,
    DeliveryKind,
    InvocationEnvelope,
    invocation_message_id,
    parse_artifact_request,
    serialize_message,
)
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpServerConfiguration,
    McpTransport,
    McpTransportServer,
)
from pydantic import SecretStr
from test_capability_routing_flow import (
    ASSET_REF,
    MISSION_REF,
    _configuration,
    _delivery,
    _make_nmap_shim,
)
from test_transport_flow import _delivery as _synthetic_delivery
from transport_test_capability import (
    TransportSyntheticCapability,
    allow_completion,
    capability_manifest,
    execution_started,
    reset_control,
)

NOW = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


class DisconnectingArtifactReceiver:
    def __init__(
        self,
        delegate: CoreArtifactReceiver,
        transport: McpTransport,
        *,
        disconnect_on: type[ArtifactChunk] | type[ArtifactTransferFinalize],
    ) -> None:
        self._delegate = delegate
        self._transport = transport
        self._disconnect_on = disconnect_on
        self.disconnected = False

    async def accept_artifact_message(self, message: bytes) -> bytes:
        request = parse_artifact_request(message)
        response = await self._delegate.accept_artifact_message(message)
        if not self.disconnected and isinstance(request, self._disconnect_on):
            self.disconnected = True
            await self._transport.disconnect()
        return response


def _synthetic_node_configuration(root: Path) -> NodeConfiguration:
    capability_path = root / "capabilities"
    capability_path.mkdir(parents=True)
    (capability_path / "capability.json").write_text(
        json.dumps(capability_manifest(), indent=2), encoding="utf-8"
    )
    return NodeConfiguration.for_runtime_directory(
        root / "runtime",
        capability_paths=(capability_path,),
        configured_node_id="node-mcp-recovery",
    )


def _record_core_run(database: CoreDatabase, run_id: str) -> None:
    delivery = _delivery(run_id)
    with database.unit_of_work() as work:
        work.missions.add(
            Mission(
                mission_ref=MISSION_REF,
                status="ACTIVE",
                created_at=NOW,
                name="MCP vertical slice",
            )
        )
        work.assets.add(
            Asset(
                asset_ref=ASSET_REF,
                mission_ref=MISSION_REF,
                kind="host",
                primary_address=delivery.assets[0].primary_address,
                created_at=NOW,
            )
        )
        work.runs.add(
            CapabilityRun(
                run_id=delivery.invocation.run_id,
                capability_id=delivery.invocation.capability_id,
                operation=delivery.invocation.operation,
                mission_ref=delivery.invocation.mission_ref,
                status=CapabilityRunStatus.CREATED,
                created_at=NOW,
            )
        )


def test_real_mcp_routed_capability_artifact_and_world_state(tmp_path: Path) -> None:
    run_id = "run-real-mcp-vertical-slice"
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    _record_core_run(database, run_id)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
    )
    artifacts = CoreArtifactService(database, storage)
    artifact_receiver = CoreArtifactReceiver(database, storage)
    ingestion = ResultIngestionService(database)
    receiver = CoreTransportReceiver(database, result_ingestion=ingestion)
    registry = CapabilityRegistry(database)
    token = SecretStr("mcp-vertical-token")
    shim = _make_nmap_shim(tmp_path)

    async def scenario() -> tuple[ArtifactRef, bytes]:
        node = ExecutionNode(
            _configuration(
                tmp_path / "node",
                node_id="node-real-mcp",
                nmap_executable=shim,
            )
        )
        await node.initialize()
        assert node.store is not None
        endpoint = ExecutionNodeTransportEndpoint(node)
        server = McpTransportServer(
            endpoint=endpoint,
            artifact_source=NodeMcpArtifactSource(
                store=node.store,
                spool_root=node.configuration.artifact_spool_root,
            ),
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
        registration = CapabilityRegistrationClient(transport, registry)
        router = CapabilityRouter(registry, transport)
        client = CoreTransportClient(transport, receiver)
        try:
            await transport.connect()
            advertisement, providers = await registration.refresh_node(endpoint.node_id)
            assert advertisement.node_id == endpoint.node_id
            assert any(
                provider.capability_id == "network.service_discovery" for provider in providers
            )
            delivery = _delivery(run_id)
            provider = router.select_provider(
                capability_id=delivery.invocation.capability_id,
                operation=delivery.invocation.operation,
            )
            await router.dispatch(
                invocation=delivery.invocation,
                delivery=delivery,
                provider=provider,
            )
            for _ in range(200):
                status = await transport.query_run_status(
                    endpoint.node_id, delivery.invocation.run_id
                )
                if status is not None and status.is_terminal:
                    break
                await asyncio.sleep(0.01)
            assert status is CapabilityRunStatus.COMPLETED

            summary = await transport.synchronize_artifacts(artifact_receiver, chunk_size=64)
            assert summary.synchronized == 1
            count = await client.flush_node(endpoint.node_id)
            assert count > 0
            for _ in range(count):
                await client.receive_one()

            result = receiver.result_for_run(delivery.invocation.run_id)
            assert result is not None
            artifact_ref = result.result.artifacts[0].artifact_id
            content = artifacts.read_bytes(artifact_ref)
            assert b"<nmaprun" in content
            with database.unit_of_work() as work:
                services = work.services.list_for_asset(ASSET_REF)
            assert tuple(sorted(service.port for service in services)) == (22, 80)
            assert node.store.pending_results() == ()
            assert node.store.pending_events() == ()
            return artifact_ref, content
        finally:
            await transport.disconnect()
            await server.stop()
            await node.shutdown()

    try:
        artifact_ref, content = asyncio.run(scenario())
        database.dispose()
        reopened = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
        upgrade_database(reopened)
        reopened_storage = FilesystemArtifactStorage(
            ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
        )
        try:
            assert (
                CoreArtifactService(reopened, reopened_storage).read_bytes(artifact_ref) == content
            )
            with reopened.unit_of_work() as work:
                assert len(work.services.list_for_asset(ASSET_REF)) == 2
        finally:
            reopened.dispose()
    finally:
        database.dispose()


def test_mcp_disconnect_duplicates_lost_ack_and_node_restart(tmp_path: Path) -> None:
    reset_control()
    configuration = _synthetic_node_configuration(tmp_path / "synthetic")
    core_path = tmp_path / "transport-core.sqlite3"
    database = CoreDatabase(DatabaseConfig.sqlite(core_path))
    upgrade_database(database)
    artifact_root = tmp_path / "recovery-core-artifacts"
    token = SecretStr("mcp-recovery-token")
    delivery = _synthetic_delivery("run-mcp-recovery", wait_for_release=True)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
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
        receiver = CoreTransportReceiver(database)
        client = CoreTransportClient(transport, receiver)
        await transport.connect()
        unsupported_delivery = _synthetic_delivery("run-mcp-unsupported")
        unsupported = InvocationEnvelope(
            protocol_version="99.0",
            message_id=invocation_message_id(unsupported_delivery.invocation.run_id),
            node_id=endpoint.node_id,
            correlation_id=unsupported_delivery.invocation.run_id,
            timestamp=datetime.now(UTC),
            delivery=unsupported_delivery,
        )
        await transport.send_serialized_invocation(endpoint.node_id, serialize_message(unsupported))
        await asyncio.sleep(0.05)
        unsupported_failure = await asyncio.wait_for(transport.receive_failure(), timeout=2)
        assert unsupported_failure.code == "UNSUPPORTED_PROTOCOL_VERSION"
        await transport.submit_invocation(endpoint.node_id, delivery)
        await transport.submit_invocation(endpoint.node_id, delivery)
        await asyncio.wait_for(execution_started.wait(), timeout=2)

        await transport.disconnect()
        allow_completion.set()
        assert node.store is not None
        for _ in range(200):
            if node.store.get_result(delivery.invocation.run_id) is not None:
                break
            await asyncio.sleep(0.01)
        assert node.store.get_result(delivery.invocation.run_id) is not None
        assert node.lifecycle.state is NodeLifecycleState.READY
        assert TransportSyntheticCapability.execution_count == 1

        await transport.connect()
        assert (
            await transport.query_run_status(endpoint.node_id, delivery.invocation.run_id)
            is CapabilityRunStatus.COMPLETED
        )
        await transport.submit_invocation(endpoint.node_id, delivery)
        await asyncio.sleep(0.05)
        assert TransportSyntheticCapability.execution_count == 1

        conflict = _synthetic_delivery(
            "run-mcp-recovery",
            message="conflicting MCP duplicate",
            wait_for_release=True,
        )
        await transport.submit_invocation(endpoint.node_id, conflict)
        await asyncio.sleep(0.05)
        failure = await asyncio.wait_for(transport.receive_failure(), timeout=2)
        assert failure.code == "CONFLICTING_INVOCATION"

        first_count = await client.flush_node(endpoint.node_id)
        assert first_count == 4
        first_kinds: set[DeliveryKind] = set()
        for _ in range(first_count):
            serialized = await transport.receive()
            record, _ack = receiver.accept(serialized)
            first_kinds.add(record.message_kind)
        assert first_kinds == {DeliveryKind.EVENT, DeliveryKind.RESULT}

        await transport.disconnect()
        await server.stop()
        await node.shutdown()

        database.dispose()
        restarted_database = CoreDatabase(DatabaseConfig.sqlite(core_path))
        upgrade_database(restarted_database)
        restarted_receiver = CoreTransportReceiver(restarted_database)
        restarted_artifact_storage = FilesystemArtifactStorage(
            ArtifactStorageConfiguration(root=artifact_root)
        )
        restarted_artifact_receiver = CoreArtifactReceiver(
            restarted_database, restarted_artifact_storage
        )
        restarted_artifact_service = CoreArtifactService(
            restarted_database, restarted_artifact_storage
        )

        restarted = ExecutionNode(configuration)
        await restarted.initialize()
        restarted_endpoint = ExecutionNodeTransportEndpoint(restarted)
        assert restarted.store is not None
        restarted_server = McpTransportServer(
            endpoint=restarted_endpoint,
            artifact_source=NodeMcpArtifactSource(
                store=restarted.store,
                spool_root=restarted.configuration.artifact_spool_root,
            ),
            configuration=McpServerConfiguration(port=0, bearer_token=token),
        )
        await restarted_server.start()
        restarted_transport = McpTransport(
            McpClientConfiguration(
                endpoint_url=restarted_server.endpoint_url,
                node_id=restarted_endpoint.node_id,
                bearer_token=token,
            )
        )
        restarted_client = CoreTransportClient(restarted_transport, restarted_receiver)
        try:
            await restarted_transport.connect()
            replay_count = await restarted_client.flush_node(restarted_endpoint.node_id)
            assert replay_count == 4
            for _ in range(replay_count):
                await restarted_client.receive_one()
            records = restarted_receiver.records_for_run(delivery.invocation.run_id)
            assert len(records) == 4
            assert all(record.delivery_count == 2 for record in records)
            assert restarted.store is not None
            assert restarted.store.pending_results() == ()
            assert restarted.store.pending_events() == ()

            artifact_record = restarted.store.list_artifacts_for_run(delivery.invocation.run_id)[0]
            artifact_ref = artifact_record.descriptor.artifact_id
            interrupted = DisconnectingArtifactReceiver(
                restarted_artifact_receiver,
                restarted_transport,
                disconnect_on=ArtifactChunk,
            )
            partial = await restarted_transport.synchronize_artifacts(interrupted, chunk_size=8)
            assert partial.failed == 1 and interrupted.disconnected
            assert not restarted_artifact_service.content_available(artifact_ref)

            await restarted_transport.connect()
            lost_ack = DisconnectingArtifactReceiver(
                restarted_artifact_receiver,
                restarted_transport,
                disconnect_on=ArtifactTransferFinalize,
            )
            completed_without_ack = await restarted_transport.synchronize_artifacts(
                lost_ack, chunk_size=8
            )
            assert completed_without_ack.failed == 1 and lost_ack.disconnected
            assert restarted_artifact_service.content_available(artifact_ref)
            pending = restarted.store.get_artifact(artifact_ref)
            assert pending is not None
            assert pending.sync_state is ArtifactSyncState.SYNC_PENDING

            await restarted_transport.connect()
            retry = await restarted_transport.synchronize_artifacts(
                restarted_artifact_receiver, chunk_size=8
            )
            assert retry.synchronized == 1
            synchronized = restarted.store.get_artifact(artifact_ref)
            assert synchronized is not None
            assert synchronized.sync_state is ArtifactSyncState.SYNCED
            assert (
                restarted_artifact_service.read_bytes(artifact_ref)
                == b"serialized transport payload"
            )

            await restarted_transport.submit_invocation(restarted_endpoint.node_id, delivery)
            await asyncio.sleep(0.05)
            assert TransportSyntheticCapability.execution_count == 1
        finally:
            await restarted_transport.disconnect()
            await restarted_server.stop()
            await restarted.shutdown()
            restarted_database.dispose()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
