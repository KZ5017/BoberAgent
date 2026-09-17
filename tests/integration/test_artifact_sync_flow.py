"""Milestone 6 end-to-end Artifact synchronization across in-memory transport."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import ArtifactRef
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
    upgrade_database,
)
from boberagent_execution_node import (
    ArtifactSyncCoordinator,
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.persistence import ArtifactSyncState
from boberagent_transport import (
    ArtifactChunk,
    ArtifactTransferFinalize,
    ArtifactTransferRequest,
    ArtifactTransferResponse,
    ArtifactTransport,
    InMemoryTransport,
    TransportDisconnected,
)
from test_transport_flow import _delivery
from transport_test_capability import capability_manifest, reset_control


def _node_configuration(tmp_path: Path) -> NodeConfiguration:
    capability_path = tmp_path / "capabilities"
    capability_path.mkdir(parents=True)
    (capability_path / "capability.json").write_text(
        json.dumps(capability_manifest(), indent=2), encoding="utf-8"
    )
    return NodeConfiguration.for_runtime_directory(
        tmp_path / "node-runtime",
        capability_paths=(capability_path,),
        configured_node_id="node-artifact-integration",
    )


def _core_components(
    tmp_path: Path,
) -> tuple[CoreDatabase, CoreArtifactService, CoreArtifactReceiver]:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
    )
    return database, CoreArtifactService(database, storage), CoreArtifactReceiver(database, storage)


def _coordinator(
    node: ExecutionNode,
    transport: ArtifactTransport,
    *,
    chunk_size: int = 4,
) -> ArtifactSyncCoordinator:
    assert node.store is not None
    assert node.identity is not None
    return ArtifactSyncCoordinator(
        store=node.store,
        spool_root=node.configuration.artifact_spool_root,
        node_id=str(node.identity.node_id),
        transport=transport,
        clock=lambda: datetime.now(UTC),
        chunk_size=chunk_size,
    )


class DisconnectAfterFirstChunk:
    def __init__(self, transport: InMemoryTransport) -> None:
        self._transport = transport
        self._disconnected = False

    @property
    def connected(self) -> bool:
        return self._transport.connected

    async def exchange_artifact(self, request: ArtifactTransferRequest) -> ArtifactTransferResponse:
        response = await self._transport.exchange_artifact(request)
        if isinstance(request, ArtifactChunk) and not self._disconnected:
            self._disconnected = True
            await self._transport.disconnect()
        return response


class LoseFinalAcknowledgement:
    def __init__(self, transport: InMemoryTransport) -> None:
        self._transport = transport
        self._lost = False

    @property
    def connected(self) -> bool:
        return self._transport.connected

    async def exchange_artifact(self, request: ArtifactTransferRequest) -> ArtifactTransferResponse:
        response = await self._transport.exchange_artifact(request)
        if isinstance(request, ArtifactTransferFinalize) and not self._lost:
            self._lost = True
            await self._transport.disconnect()
            raise TransportDisconnected("simulated lost Artifact acknowledgement")
        return response


def test_full_capability_result_artifact_sync_and_core_restart(tmp_path: Path) -> None:
    reset_control()
    database, artifact_service, artifact_receiver = _core_components(tmp_path)
    configuration = _node_configuration(tmp_path)
    delivery = _delivery("run-artifact-e2e", message="artifact transport evidence")

    async def scenario() -> ArtifactRef:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)
        transport.register_artifact_receiver(artifact_receiver)
        result_receiver = CoreTransportReceiver(database)
        client = CoreTransportClient(transport, result_receiver)
        await transport.connect()

        await client.submit_invocation(endpoint.node_id, delivery)
        await transport.wait_for_idle()
        assert await client.flush_node(endpoint.node_id) == 4
        for _ in range(4):
            await client.receive_one()
        result_envelope = result_receiver.result_for_run(delivery.invocation.run_id)
        assert result_envelope is not None
        artifact_ref = result_envelope.result.artifacts[0].artifact_id
        assert artifact_service.get(artifact_ref) is None

        outcomes = await _coordinator(node, transport).synchronize_pending()
        assert len(outcomes) == 1
        assert outcomes[0].synchronized
        assert node.store is not None
        spool_record = node.store.get_artifact(artifact_ref)
        assert spool_record is not None
        assert spool_record.sync_state is ArtifactSyncState.SYNCED
        assert artifact_service.read_bytes(artifact_ref) == b"artifact transport evidence"
        core_record = artifact_service.get(artifact_ref)
        assert core_record is not None
        assert core_record.descriptor.artifact_id == artifact_ref
        assert core_record.descriptor == result_envelope.result.artifacts[0]

        await transport.disconnect()
        await node.shutdown()
        return artifact_ref

    artifact_ref = asyncio.run(scenario())
    database.dispose()

    reopened, restarted_service, _receiver = _core_components(tmp_path)
    try:
        assert restarted_service.read_bytes(artifact_ref) == b"artifact transport evidence"
    finally:
        reopened.dispose()


def test_disconnect_partial_transfer_resumes_without_exposing_partial_bytes(
    tmp_path: Path,
) -> None:
    reset_control()
    database, artifact_service, artifact_receiver = _core_components(tmp_path)
    configuration = _node_configuration(tmp_path)
    delivery = _delivery("run-artifact-disconnect", message="many chunks for reconnect")

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)
        transport.register_artifact_receiver(artifact_receiver)
        await transport.connect()
        await transport.submit_invocation(endpoint.node_id, delivery)
        await transport.wait_for_idle()
        assert node.store is not None
        result = node.store.get_result(delivery.invocation.run_id)
        assert result is not None
        artifact_ref = result.artifacts[0].artifact_id

        interrupted = await _coordinator(
            node, DisconnectAfterFirstChunk(transport), chunk_size=4
        ).synchronize(artifact_ref)
        assert not interrupted.synchronized
        assert not artifact_service.content_available(artifact_ref)
        record = node.store.get_artifact(artifact_ref)
        assert record is not None
        assert record.sync_state is ArtifactSyncState.SYNC_FAILED

        await transport.connect()
        resumed = await _coordinator(node, transport, chunk_size=4).synchronize_pending()
        assert resumed[0].synchronized
        assert artifact_service.read_bytes(artifact_ref) == b"many chunks for reconnect"
        record = node.store.get_artifact(artifact_ref)
        assert record is not None
        assert record.sync_attempt_count == 2
        assert record.sync_state is ArtifactSyncState.SYNCED
        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_lost_acknowledgement_is_idempotent_and_node_restart_preserves_pending(
    tmp_path: Path,
) -> None:
    reset_control()
    database, artifact_service, artifact_receiver = _core_components(tmp_path)
    configuration = _node_configuration(tmp_path)
    delivery = _delivery("run-artifact-restart", message="survives node restart")

    async def scenario() -> None:
        first = ExecutionNode(configuration)
        await first.initialize()
        first_endpoint = ExecutionNodeTransportEndpoint(first)
        transport = InMemoryTransport()
        transport.register_node(first_endpoint)
        transport.register_artifact_receiver(artifact_receiver)
        await transport.connect()
        await transport.submit_invocation(first_endpoint.node_id, delivery)
        await transport.wait_for_idle()
        assert first.store is not None
        result = first.store.get_result(delivery.invocation.run_id)
        assert result is not None
        artifact_ref = result.artifacts[0].artifact_id
        first.store.begin_artifact_sync(artifact_ref, datetime.now(UTC))
        pending = first.store.get_artifact(artifact_ref)
        assert pending is not None
        assert pending.sync_state is ArtifactSyncState.SYNC_PENDING
        await transport.disconnect()
        await first.shutdown()

        restarted = ExecutionNode(configuration)
        await restarted.initialize()
        restarted_endpoint = ExecutionNodeTransportEndpoint(restarted)
        transport.register_node(restarted_endpoint, replace=True)
        await transport.connect()
        assert restarted.store is not None
        recovered = restarted.store.get_artifact(artifact_ref)
        assert recovered is not None
        assert recovered.descriptor.artifact_id == artifact_ref
        assert recovered.sync_state is ArtifactSyncState.SYNC_PENDING
        lost = await _coordinator(
            restarted, LoseFinalAcknowledgement(transport), chunk_size=5
        ).synchronize(artifact_ref)
        assert not lost.synchronized
        assert artifact_service.read_bytes(artifact_ref) == b"survives node restart"
        assert restarted.store is not None
        failed = restarted.store.get_artifact(artifact_ref)
        assert failed is not None
        assert failed.sync_state is ArtifactSyncState.SYNC_FAILED

        await transport.connect()
        replay = await _coordinator(restarted, transport, chunk_size=5).synchronize_pending()
        assert replay[0].synchronized
        assert replay[0].code == "ALREADY_SYNCHRONIZED"
        synced = restarted.store.get_artifact(artifact_ref)
        assert synced is not None
        assert synced.sync_attempt_count == 3
        assert synced.sync_state is ArtifactSyncState.SYNCED
        await transport.disconnect()
        await restarted.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_corrupt_spool_content_leaves_clear_failed_state(tmp_path: Path) -> None:
    reset_control()
    database, artifact_service, artifact_receiver = _core_components(tmp_path)
    configuration = _node_configuration(tmp_path)
    delivery = _delivery("run-artifact-corrupt", message="original bytes")

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)
        transport.register_artifact_receiver(artifact_receiver)
        await transport.connect()
        await transport.submit_invocation(endpoint.node_id, delivery)
        await transport.wait_for_idle()
        assert node.store is not None
        result = node.store.get_result(delivery.invocation.run_id)
        assert result is not None
        artifact_ref = result.artifacts[0].artifact_id
        record = node.store.get_artifact(artifact_ref)
        assert record is not None
        Path(record.local_path).write_bytes(b"tampered bytes")

        outcome = await _coordinator(node, transport).synchronize(artifact_ref)
        assert not outcome.synchronized
        assert outcome.code == "INTEGRITY_MISMATCH"
        failed = node.store.get_artifact(artifact_ref)
        assert failed is not None
        assert failed.sync_state is ArtifactSyncState.SYNC_FAILED
        assert failed.sync_error is not None
        assert "INTEGRITY_MISMATCH" in failed.sync_error
        assert not artifact_service.content_available(artifact_ref)
        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
