"""E3 imports opaque synthetic retained bytes after a routed, admitted Run."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import CapabilityRunStatus
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRouter,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    current_revision,
    upgrade_database,
)
from boberagent_core.planning.approval import CorePlanApprovalService
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.preparation import (
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
    PreparationDispatchError,
    PreparationLifecycle,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import current_revision as node_revision
from boberagent_execution_node.persistence.migrations import (
    upgrade_database as upgrade_node_database,
)
from boberagent_transport import (
    ImportChunk,
    InMemoryTransport,
    TransportDisconnected,
    parse_advertisement,
    serialize_message,
)
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpServerConfiguration,
    McpTransport,
    McpTransportServer,
)
from pydantic import SecretStr
from sqlalchemy import inspect
from test_planning_policy import _profile
from test_runtime_preparation_e2 import NODE, _setup


def test_synthetic_e2_to_e3_exact_import_reopen_and_replay(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, _old_service, request = _setup(tmp_path)
    asyncio.run(_synthetic_flow(tmp_path, database, policy, approvals, registry, request))


def test_e3_forward_migrations_preserve_prior_schema(tmp_path: Path) -> None:
    core = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core-upgrade.sqlite3"))
    node = RuntimeDatabase(tmp_path / "node-upgrade.sqlite3")
    try:
        upgrade_database(core, "0016_m20_e2_preparation")
        upgrade_node_database(node, "0005_durable_interactions")
        assert (
            "preparation_import_progress" not in inspect(core._migration_engine).get_table_names()
        )
        assert "preparation_authorities" not in inspect(node.migration_engine).get_table_names()
        upgrade_database(core)
        upgrade_node_database(node)
        assert current_revision(core) == "0017_m20_e3_import_progress"
        assert node_revision(node) == "0006_preparation_import"
        assert "preparation_import_progress" in inspect(core._migration_engine).get_table_names()
        assert {"preparation_authorities", "preparation_imports", "imported_artifacts"} <= set(
            inspect(node.migration_engine).get_table_names()
        )
    finally:
        core.dispose()
        node.close()


class _LoseFirstChunkAck(InMemoryTransport):
    def __init__(self) -> None:
        super().__init__(trusted_core_principal="boberagent-core")
        self.lost = False

    async def exchange_preparation_import(self, request):  # type: ignore[no-untyped-def]
        reply = await super().exchange_preparation_import(request)
        if isinstance(request, ImportChunk) and not self.lost:
            self.lost = True
            await self.disconnect()
            raise TransportDisconnected("simulated lost first chunk acknowledgement")
        return reply


def test_disconnect_core_and_node_reopen_resume_one_import(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, _old_service, request = _setup(tmp_path)

    async def scenario() -> None:
        config = NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        node = ExecutionNode(config)
        await node.initialize()
        transport = _LoseFirstChunkAck()
        transport.register_node(ExecutionNodeTransportEndpoint(node))
        await transport.connect()

        def clock() -> datetime:
            return datetime.now(UTC)

        admission = CoreRuntimePreparationAdmissionService(
            database, policy, approvals, registry, clock=clock
        )
        admitted = admission.admit(request)
        assert admitted.permit is not None
        artifacts = CoreArtifactService(
            database,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
        )
        dispatch = CorePreparationDispatchService(
            database,
            admission,
            registry,
            CapabilityRouter(registry, transport, clock=clock),
            transport,
            artifacts,
            clock=clock,
        )
        try:
            with pytest.raises(TransportDisconnected, match="lost first chunk"):
                await dispatch.dispatch_and_import(admitted.attempt.preparation_ref, chunk_size=19)
            assert transport.lost
            assert node.preparation is not None
            with pytest.raises(FileNotFoundError):
                node.preparation.imported_bytes(
                    admitted.permit.spec.source.plan_source.raw_artifact_ref
                )
            await node.shutdown()
            node = ExecutionNode(config)
            await node.initialize()
            transport.register_node(ExecutionNodeTransportEndpoint(node), replace=True)
            await transport.connect()
            database.dispose()
            reopened = CoreDatabase(database.config)
            try:
                fresh_policy = CorePlanPolicyService(reopened, policy._registry, clock=clock)
                fresh_registry = type(registry)(reopened, clock=clock)
                fresh_admission = CoreRuntimePreparationAdmissionService(
                    reopened,
                    fresh_policy,
                    CorePlanApprovalService(reopened, fresh_policy, clock=clock),
                    fresh_registry,
                    clock=clock,
                )
                fresh_artifacts = CoreArtifactService(
                    reopened,
                    FilesystemArtifactStorage(
                        ArtifactStorageConfiguration(root=tmp_path / "artifacts")
                    ),
                )
                resumed = CorePreparationDispatchService(
                    reopened,
                    fresh_admission,
                    fresh_registry,
                    CapabilityRouter(fresh_registry, transport, clock=clock),
                    transport,
                    fresh_artifacts,
                    clock=clock,
                )
                progress = await resumed.dispatch_and_import(
                    admitted.attempt.preparation_ref, chunk_size=17
                )
                assert all(item.state.value == "VERIFIED" for item in progress)
                assert node.preparation is not None
                assert node.preparation.imported_bytes(
                    admitted.permit.spec.source.plan_source.raw_artifact_ref
                ) == fresh_artifacts.read_bytes(
                    admitted.permit.spec.source.plan_source.raw_artifact_ref
                )
                with reopened.unit_of_work() as work:
                    assert work.runs.get(admitted.permit.run_ref) is not None
            finally:
                reopened.dispose()
        finally:
            await transport.disconnect()
            await node.shutdown()
            database.dispose()

    asyncio.run(scenario())


def test_stale_policy_and_unsupported_import_protocol_stop_before_run(tmp_path: Path) -> None:
    database, plan, policy, approvals, registry, _old_service, request = _setup(tmp_path)

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        )
        await node.initialize()
        transport = InMemoryTransport(trusted_core_principal="boberagent-core")

        class OldProtocolEndpoint(ExecutionNodeTransportEndpoint):
            async def handshake(self, message: bytes) -> bytes:
                advertisement = parse_advertisement(await super().handshake(message))
                return serialize_message(
                    advertisement.model_copy(update={"preparation_import_versions": ()})
                )

        transport.register_node(OldProtocolEndpoint(node))
        await transport.connect()

        def clock() -> datetime:
            return datetime.now(UTC)

        admission = CoreRuntimePreparationAdmissionService(
            database, policy, approvals, registry, clock=clock
        )
        permit = admission.admit(request).permit
        assert permit is not None
        artifacts = CoreArtifactService(
            database,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
        )
        dispatch = CorePreparationDispatchService(
            database,
            admission,
            registry,
            CapabilityRouter(registry, transport, clock=clock),
            transport,
            artifacts,
        )
        try:
            with pytest.raises(PreparationDispatchError, match="PREPARATION_PROTOCOL_UNSUPPORTED"):
                await dispatch.dispatch_and_import(permit.spec.preparation_ref)
            changed = _profile(plan, approval=False).model_copy(
                update={"require_operator_approval": True}
            )
            stale_policy = CorePlanPolicyService(
                database, PolicyProfileRegistry((changed,)), clock=clock
            )
            stale = CoreRuntimePreparationAdmissionService(
                database, stale_policy, approvals, registry, clock=clock
            )
            transport.register_node(ExecutionNodeTransportEndpoint(node), replace=True)
            stale_dispatch = CorePreparationDispatchService(
                database,
                stale,
                registry,
                CapabilityRouter(registry, transport, clock=clock),
                transport,
                artifacts,
            )
            with pytest.raises(PreparationDispatchError, match="PREPARATION_AUTHORITY_STALE"):
                await stale_dispatch.dispatch_and_import(permit.spec.preparation_ref)
            with database.unit_of_work() as work:
                assert work.runs.get(permit.run_ref) is None
            assert node.store is not None and node.store.get_run(permit.run_ref) is None
        finally:
            await transport.disconnect()
            await node.shutdown()
            database.dispose()

    asyncio.run(scenario())


async def _synthetic_flow(  # type: ignore[no-untyped-def]
    tmp_path: Path, database, policy, approvals, registry, request
) -> None:
    node = ExecutionNode(
        NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
    )
    await node.initialize()
    transport = InMemoryTransport(trusted_core_principal="boberagent-core")
    transport.register_node(ExecutionNodeTransportEndpoint(node))
    await transport.connect()

    def clock() -> datetime:
        return datetime.now(UTC)

    admission = CoreRuntimePreparationAdmissionService(
        database, policy, approvals, registry, clock=clock
    )
    admitted = admission.admit(request)
    assert admitted.permit is not None
    artifacts = CoreArtifactService(
        database,
        FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
    )
    dispatch = CorePreparationDispatchService(
        database,
        admission,
        registry,
        CapabilityRouter(registry, transport, clock=clock),
        transport,
        artifacts,
        clock=clock,
    )
    try:
        first = await asyncio.wait_for(
            dispatch.dispatch_and_import(admitted.attempt.preparation_ref, chunk_size=23),
            timeout=15,
        )
        assert all(item.state.value == "VERIFIED" for item in first)
        run_ref = admitted.permit.run_ref
        with database.unit_of_work() as work:
            run = work.runs.get(run_ref)
            assert run is not None and run.status is CapabilityRunStatus.QUEUED
            attempt = work.runtime_preparations.get(admitted.attempt.preparation_ref)
            assert attempt is not None and attempt.lifecycle is PreparationLifecycle.DISPATCHED
        source = admitted.permit.spec.source
        assert node.preparation is not None
        for ref in (source.plan_source.raw_artifact_ref, source.plan_source.manifest_artifact_ref):
            assert node.preparation.imported_bytes(ref) == artifacts.read_bytes(ref)
            assert node.store is not None and node.store.get_artifact(ref) is None
        again = await dispatch.dispatch_and_import(admitted.attempt.preparation_ref, chunk_size=17)
        assert again == first
        await node.shutdown()
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        )
        await node.initialize()
        assert node.preparation is not None
        assert node.preparation.imported_bytes(
            source.plan_source.raw_artifact_ref
        ) == artifacts.read_bytes(source.plan_source.raw_artifact_ref)
        await transport.disconnect()
        transport.register_node(ExecutionNodeTransportEndpoint(node), replace=True)
        await transport.connect()
        assert await dispatch.dispatch_and_import(admitted.attempt.preparation_ref) == first
        database.dispose()
        reopened = CoreDatabase(database.config)
        try:
            with reopened.unit_of_work() as work:
                assert work.runs.get(run_ref) is not None
                assert work.preparation_imports.get(first[0].import_id) == first[0]
        finally:
            reopened.dispose()
    finally:
        await transport.disconnect()
        await node.shutdown()
        database.dispose()


def test_direct_local_runtime_preparation_is_denied(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, _old_service, request = _setup(tmp_path)
    asyncio.run(_local_denial(tmp_path, database, policy, approvals, registry, request))


def test_real_loopback_mcp_carries_authenticated_e3_import(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, _old_service, request = _setup(tmp_path)

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        )
        await node.initialize()
        token = SecretStr("harmless-e3-loopback-token")
        server = McpTransportServer(
            endpoint=ExecutionNodeTransportEndpoint(node),
            configuration=McpServerConfiguration(port=0, bearer_token=token),
        )
        await server.start()
        transport = McpTransport(
            McpClientConfiguration(
                endpoint_url=server.endpoint_url,
                node_id=NODE,
                bearer_token=token,
            )
        )

        def clock() -> datetime:
            return datetime.now(UTC)

        try:
            await transport.connect()
            admission = CoreRuntimePreparationAdmissionService(
                database, policy, approvals, registry, clock=clock
            )
            # The real handshake supplies the authority and import capability metadata.
            from boberagent_core.capabilities import CapabilityRegistrationClient

            await CapabilityRegistrationClient(transport, registry).refresh_node(NODE)
            admitted = admission.admit(request)
            assert admitted.permit is not None
            artifacts = CoreArtifactService(
                database,
                FilesystemArtifactStorage(
                    ArtifactStorageConfiguration(root=tmp_path / "artifacts")
                ),
            )
            dispatch = CorePreparationDispatchService(
                database,
                admission,
                registry,
                CapabilityRouter(registry, transport, clock=clock),
                transport,
                artifacts,
                clock=clock,
            )
            progress = await asyncio.wait_for(
                dispatch.dispatch_and_import(admitted.attempt.preparation_ref, chunk_size=31),
                timeout=30,
            )
            assert all(item.state.value == "VERIFIED" for item in progress)
            assert node.preparation is not None
            for item in progress:
                assert node.preparation.imported_bytes(item.artifact_ref) == artifacts.read_bytes(
                    item.artifact_ref
                )
        finally:
            await transport.disconnect()
            await server.stop()
            await node.shutdown()
            database.dispose()

    asyncio.run(scenario())


async def _local_denial(  # type: ignore[no-untyped-def]
    tmp_path: Path, database, policy, approvals, registry, request
) -> None:
    node = ExecutionNode(
        NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
    )
    await node.initialize()
    try:
        admission = CoreRuntimePreparationAdmissionService(
            database, policy, approvals, registry, clock=lambda: datetime.now(UTC)
        )
        permit = admission.admit(request).permit
        assert permit is not None
        from boberagent_contracts import CapabilityInvocation, RuntimePreparationInput
        from boberagent_execution_node.services import LocalInvocationEnvironment
        from boberagent_sdk import MissionContext

        invocation = CapabilityInvocation(
            run_id=permit.run_ref,
            capability_id="runtime.prepare",
            operation="prepare",
            mission_ref=permit.spec.mission_ref,
            inputs=RuntimePreparationInput(
                schema_version="runtime-preparation-input-v1", permit=permit
            ).model_dump(mode="json"),
        )
        environment = LocalInvocationEnvironment(
            mission=MissionContext(mission_ref=permit.spec.mission_ref)
        )
        with pytest.raises(ValueError, match="TRUSTED_PREPARATION_ADMISSION_REQUIRED"):
            await node.execute_local(invocation, environment)
        assert node.store is not None and node.store.get_run(permit.run_ref) is None
    finally:
        await node.shutdown()
        database.dispose()
