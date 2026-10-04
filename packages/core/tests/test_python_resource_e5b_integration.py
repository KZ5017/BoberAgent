"""Existing C/D→E2/E3/E4 chain admits E5-B bookkeeping without new dispatch."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import (
    PythonProviderPhase,
    PythonResourceState,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeProfileIdentity,
    PythonRuntimeRequestBinding,
    preparation_permit_digest,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRouter,
    CoreArtifactService,
    FilesystemArtifactStorage,
)
from boberagent_core.preparation import (
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.persistence.orm import RunRow, WorkspaceRow
from boberagent_transport import InMemoryTransport
from sqlalchemy import func, select
from test_runtime_preparation_e2 import NODE, _setup
from test_runtime_preparation_e4 import ControlledConfinement


def test_existing_admitted_source_can_reserve_resource_without_new_run_or_workspace(
    tmp_path: Path,
) -> None:
    database, _plan, policy, approvals, registry, _old, request = _setup(tmp_path)

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE),
            preparation_confinement=ControlledConfinement(),
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
        permit = admitted.permit
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
            # All source operations below are existing E3/E4 behavior, not E5-B work.
            await dispatch.dispatch_and_import(admitted.attempt.preparation_ref)
            evidence = await dispatch.materialize_source(admitted.attempt.preparation_ref)
            assert node.python_resources is not None and node.database is not None
            authority = PythonRuntimeAuthorityProjection(
                permit=permit,
                binding=PythonRuntimeRequestBinding(
                    schema_version="python-runtime-request-binding-v1",
                    spec=permit.spec,
                    permit_ref=permit.permit_ref,
                    permit_sha256=preparation_permit_digest(permit),
                    run_ref=permit.run_ref,
                    materialization_id=evidence.materialization_id,
                    source_tree_sha256=evidence.tree_sha256,
                    entrypoint_sha256=permit.spec.entrypoint.entry_sha256,
                    profile=PythonRuntimeProfileIdentity(
                        profile_id=permit.spec.profile.profile_id,
                        profile_version="1",
                        profile_sha256=permit.spec.profile_sha256,
                        runtime_provider="python-stdlib@1",
                        construction_version="python-stdlib@1",
                        layout_version="m20-e5-python-layout@1",
                    ),
                ),
            )
            before = tuple(node.configuration.workspace_root.rglob("*"))
            reserved = node.python_resources.reserve(authority, principal_id="boberagent-core")
            assert reserved.phase is PythonProviderPhase.RESERVED
            assert reserved.state is PythonResourceState.CREATING
            assert (
                node.python_resources.reserve(authority, principal_id="boberagent-core") == reserved
            )
            assert tuple(node.configuration.workspace_root.rglob("*")) == before
            with node.database.transaction() as session:
                assert session.scalar(select(func.count()).select_from(RunRow)) == 1
                assert session.scalar(select(func.count()).select_from(WorkspaceRow)) == 0
        finally:
            await transport.disconnect()
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
