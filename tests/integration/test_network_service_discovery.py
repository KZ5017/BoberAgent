"""Production service-discovery Capability through the real local Node runtime."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import (
    AssetRef,
    CapabilityInvocation,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    NetworkServiceValue,
    upgrade_database,
)
from boberagent_execution_node import (
    ArtifactSyncCoordinator,
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    LocalInvocationEnvironment,
    NodeConfiguration,
    NodeLifecycleState,
    ToolConfiguration,
)
from boberagent_execution_node.persistence import ArtifactSyncState
from boberagent_sdk import AssetSnapshot, MissionContext
from boberagent_transport import InMemoryTransport

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_ROOT = REPOSITORY_ROOT / "capabilities" / "network-service-discovery"
SHIM_FIXTURE = CAPABILITY_ROOT / "tests" / "fixtures" / "nmap_shim.py"
MISSION_REF = MissionRef("mission-network-discovery")
ASSET_REF = AssetRef("asset-network-discovery")
ADDRESS = "192.0.2.25"


def _make_nmap_shim(tmp_path: Path) -> Path:
    target = tmp_path / "nmap-test-shim"
    source_lines = SHIM_FIXTURE.read_text(encoding="utf-8").splitlines()
    source_lines[0] = f"#!{sys.executable}"
    target.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    target.chmod(0o700)
    return target


def _environment() -> LocalInvocationEnvironment:
    asset = AssetSnapshot(ref=ASSET_REF, primary_address=ADDRESS)
    return LocalInvocationEnvironment(
        mission=MissionContext(mission_ref=MISSION_REF, name="Discovery integration"),
        allowed_assets=frozenset({ASSET_REF}),
        allowed_addresses=frozenset({ADDRESS}),
        entities=(asset,),
    )


def _invocation(run_id: str) -> CapabilityInvocation:
    return CapabilityInvocation(
        run_id=CapabilityRunRef(run_id),
        capability_id="network.service_discovery",
        operation="discover",
        mission_ref=MISSION_REF,
        inputs={
            "asset_ref": str(ASSET_REF),
            "profile": "standard",
            "timeout_seconds": 10,
        },
    )


def test_real_capability_loads_executes_and_syncs_evidence(tmp_path: Path) -> None:
    shim = _make_nmap_shim(tmp_path)
    configuration = NodeConfiguration.for_runtime_directory(
        tmp_path / "node-runtime",
        capability_paths=(CAPABILITY_ROOT,),
        tools={"nmap": ToolConfiguration(executable=str(shim))},
        configured_node_id="node-network-discovery",
    )
    core_database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(core_database)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
    )
    core_artifacts = CoreArtifactService(core_database, storage)
    receiver = CoreArtifactReceiver(core_database, storage)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        health = await node.initialize()
        assert health.lifecycle is NodeLifecycleState.READY
        provider = node.capabilities.get("network.service_discovery")
        assert provider.definition.implementation_version == "0.1.0"
        assert provider.definition.dependencies[0].identifier == "nmap"

        invocation = _invocation("run-network-discovery")
        result = await node.execute_local(invocation, _environment())

        assert result.execution_status is CapabilityRunStatus.COMPLETED
        assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
        values = [observation.value for observation in result.observations]
        assert all(isinstance(value, dict) for value in values)
        assert [value["port"] for value in values if isinstance(value, dict)] == [22, 80]
        assert all(observation.type == "network.service" for observation in result.observations)
        for observation in result.observations:
            NetworkServiceValue.model_validate(observation.value)
        assert node.store is not None
        assert len(node.store.list_processes_for_run(invocation.run_id)) == 1
        assert node.results is not None
        assert len(node.results.pending()) == 1
        artifact = result.artifacts[0]
        spool_record = node.store.get_artifact(artifact.artifact_id)
        assert spool_record is not None
        assert spool_record.sync_state is ArtifactSyncState.LOCAL_ONLY
        assert Path(spool_record.local_path).read_bytes().startswith(b"<?xml")
        workspaces = node.store.list_workspaces_for_owner(str(invocation.run_id))
        assert len(workspaces) == 1
        assert Path(spool_record.local_path).is_relative_to(configuration.artifact_spool_root)

        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)
        transport.register_artifact_receiver(receiver)
        await transport.connect()
        coordinator = ArtifactSyncCoordinator(
            store=node.store,
            spool_root=configuration.artifact_spool_root,
            node_id=endpoint.node_id,
            transport=transport,
            clock=lambda: datetime.now(UTC),
            chunk_size=64,
        )
        sync_result = await coordinator.synchronize(artifact.artifact_id)
        assert sync_result.synchronized
        assert (
            core_artifacts.read_bytes(artifact.artifact_id)
            == Path(spool_record.local_path).read_bytes()
        )
        synchronized = node.store.get_artifact(artifact.artifact_id)
        assert synchronized is not None
        assert synchronized.sync_state is ArtifactSyncState.SYNCED

        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        core_database.dispose()


def test_missing_nmap_dependency_fails_before_capability_import_or_process(
    tmp_path: Path,
) -> None:
    configuration = NodeConfiguration.for_runtime_directory(
        tmp_path / "node-runtime",
        capability_paths=(CAPABILITY_ROOT,),
    )

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        health = await node.initialize()
        assert health.lifecycle is NodeLifecycleState.DEGRADED
        provider = node.capabilities.get("network.service_discovery")
        assert provider.failure is None

        invocation = _invocation("run-network-discovery-missing-nmap")
        result = await node.execute_local(invocation, _environment())
        assert result.execution_status is CapabilityRunStatus.FAILED
        assert result.diagnostics[0].code == "DEPENDENCY_UNAVAILABLE"
        assert provider.failure is None
        assert node.store is not None
        assert node.store.list_processes_for_run(invocation.run_id) == ()
        await node.shutdown()

    asyncio.run(scenario())
