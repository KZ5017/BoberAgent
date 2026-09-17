"""Milestone 9 complete routed capability-to-World-State vertical slice."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import ArtifactRef, CapabilityRun, CapabilityRunStatus
from boberagent_core import (
    ArtifactContentState,
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
    ResultIngestionStatus,
    Service,
    upgrade_database,
)
from boberagent_execution_node import (
    ArtifactSyncCoordinator,
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
)
from boberagent_transport import InMemoryTransport
from test_capability_routing_flow import (
    ASSET_REF,
    MISSION_REF,
    _configuration,
    _delivery,
    _make_nmap_shim,
)

NOW = datetime(2026, 7, 8, 9, 10, 11, tzinfo=UTC)


def _record_invocation_state(database: CoreDatabase, run_id: str) -> None:
    delivery = _delivery(run_id)
    with database.unit_of_work() as work:
        work.missions.add(
            Mission(
                mission_ref=MISSION_REF,
                status="ACTIVE",
                created_at=NOW,
                name="Milestone 9 vertical slice",
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


def _artifact_components(
    database: CoreDatabase, root: Path
) -> tuple[CoreArtifactService, CoreArtifactReceiver]:
    storage = FilesystemArtifactStorage(ArtifactStorageConfiguration(root=root))
    return CoreArtifactService(database, storage), CoreArtifactReceiver(database, storage)


def _sync_coordinator(node: ExecutionNode, transport: InMemoryTransport) -> ArtifactSyncCoordinator:
    assert node.store is not None
    assert node.identity is not None
    return ArtifactSyncCoordinator(
        store=node.store,
        spool_root=node.configuration.artifact_spool_root,
        node_id=str(node.identity.node_id),
        transport=transport,
        clock=lambda: datetime.now(UTC),
        chunk_size=64,
    )


def test_routed_result_is_ingested_materialized_deduplicated_and_survives_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "core.sqlite3"
    content_root = tmp_path / "core-artifacts"
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    run_id = "run-result-world-state"
    _record_invocation_state(database, run_id)
    artifact_service, artifact_receiver = _artifact_components(database, content_root)
    ingestion = ResultIngestionService(database)
    registry = CapabilityRegistry(database)
    transport = InMemoryTransport(queue_capacity=30)
    registration = CapabilityRegistrationClient(transport, registry)
    receiver = CoreTransportReceiver(database, result_ingestion=ingestion)
    client = CoreTransportClient(transport, receiver)
    router = CapabilityRouter(registry, transport)
    shim = _make_nmap_shim(tmp_path)

    async def scenario() -> tuple[str, str]:
        node = ExecutionNode(
            _configuration(
                tmp_path / "node",
                node_id="node-result-ingestion",
                nmap_executable=shim,
            )
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport.register_node(endpoint)
        transport.register_artifact_receiver(artifact_receiver)
        await transport.connect()
        await registration.refresh_node(endpoint.node_id)

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
        await transport.wait_for_idle()

        first_delivery_count = await client.flush_node(endpoint.node_id)
        assert first_delivery_count > 0
        for _ in range(first_delivery_count):
            await client.receive_one(acknowledge=False)

        result_envelope = receiver.result_for_run(delivery.invocation.run_id)
        assert result_envelope is not None
        result = result_envelope.result
        assert result.observations
        artifact_ref = result.artifacts[0].artifact_id
        assert artifact_service.get(artifact_ref) is not None
        assert not artifact_service.content_available(artifact_ref)

        services = tuple(sorted(ingested.port for ingested in _services(database)))
        assert services == (22, 80)
        stored = ingestion.get_ingestion(delivery.invocation.run_id)
        assert stored is not None
        assert stored.status is ResultIngestionStatus.PROCESSED
        assert stored.materialized_count == 2
        assert stored.result == result

        replay_count = await client.flush_node(endpoint.node_id)
        assert replay_count == first_delivery_count
        for _ in range(replay_count):
            await client.receive_one()
        replayed = ingestion.get_ingestion(delivery.invocation.run_id)
        assert replayed is not None
        assert replayed.processing_attempts == 1
        assert len(_services(database)) == 2
        with database.unit_of_work() as work:
            observations = tuple(
                work.observations.get(observation.observation_id)
                for observation in result.observations
            )
            inbox = work.transport_inbox.list_for_run(delivery.invocation.run_id)
        assert all(observation is not None for observation in observations)
        result_records = [record for record in inbox if record.message_kind.value == "result"]
        assert len(result_records) == 1 and result_records[0].delivery_count == 2

        sync = await _sync_coordinator(node, transport).synchronize_pending()
        assert len(sync) == 1 and sync[0].synchronized
        assert artifact_service.content_available(artifact_ref)
        assert b"<nmaprun" in artifact_service.read_bytes(artifact_ref)

        materialized = _services(database)
        by_port = {service.port: service for service in materialized}
        assert (by_port[22].service, by_port[22].product, by_port[22].version) == (
            "ssh",
            "OpenSSH",
            "9.6",
        )
        current = by_port[22]
        with database.unit_of_work() as work:
            observation = work.observations.get(current.current_observation_ref)
            run = work.runs.get(delivery.invocation.run_id)
        assert observation is not None
        assert observation.observation.run_ref == delivery.invocation.run_id
        assert observation.observation.evidence_refs == (artifact_ref,)
        assert run is not None and run.status is CapabilityRunStatus.COMPLETED

        await transport.disconnect()
        await node.shutdown()
        return str(artifact_ref), str(current.current_observation_ref)

    artifact_id, observation_id = asyncio.run(scenario())
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(reopened)
    try:
        restarted_artifacts, _receiver = _artifact_components(reopened, content_root)
        restarted_ingestion = ResultIngestionService(reopened)
        assert b"<nmaprun" in restarted_artifacts.read_bytes(ArtifactRef(artifact_id))
        assert restarted_ingestion.get_ingestion(_delivery(run_id).invocation.run_id) is not None
        services = _services(reopened)
        assert len(services) == 2
        assert any(str(ref) == observation_id for ref in services[0].provenance_refs) or any(
            str(ref) == observation_id for ref in services[1].provenance_refs
        )
    finally:
        reopened.dispose()


def test_artifact_can_arrive_before_result_ingestion(tmp_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core-before.sqlite3"))
    upgrade_database(database)
    run_id = "run-artifact-before-result"
    _record_invocation_state(database, run_id)
    artifact_service, artifact_receiver = _artifact_components(
        database, tmp_path / "core-before-artifacts"
    )
    ingestion = ResultIngestionService(database)
    registry = CapabilityRegistry(database)
    transport = InMemoryTransport(queue_capacity=30)
    receiver = CoreTransportReceiver(database, result_ingestion=ingestion)
    client = CoreTransportClient(transport, receiver)
    router = CapabilityRouter(registry, transport)
    registration = CapabilityRegistrationClient(transport, registry)
    shim = _make_nmap_shim(tmp_path)

    async def scenario() -> None:
        node = ExecutionNode(
            _configuration(
                tmp_path / "node-before",
                node_id="node-artifact-before-result",
                nmap_executable=shim,
            )
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport.register_node(endpoint)
        transport.register_artifact_receiver(artifact_receiver)
        await transport.connect()
        await registration.refresh_node(endpoint.node_id)
        delivery = _delivery(run_id)
        provider = router.select_provider(
            capability_id=delivery.invocation.capability_id,
            operation=delivery.invocation.operation,
        )
        await router.dispatch(invocation=delivery.invocation, delivery=delivery, provider=provider)
        await transport.wait_for_idle()

        assert node.store is not None
        node_result = node.store.get_result(delivery.invocation.run_id)
        assert node_result is not None
        artifact_ref = node_result.artifacts[0].artifact_id
        synced = await _sync_coordinator(node, transport).synchronize_pending()
        assert synced[0].synchronized
        assert artifact_service.content_available(artifact_ref)

        count = await client.flush_node(endpoint.node_id)
        for _ in range(count):
            await client.receive_one()
        record = artifact_service.get(artifact_ref)
        assert record is not None and record.content_state is ArtifactContentState.AVAILABLE
        assert len(_services(database)) == 2

        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def _services(database: CoreDatabase) -> tuple[Service, ...]:
    with database.unit_of_work() as work:
        return work.services.list_for_asset(ASSET_REF)
