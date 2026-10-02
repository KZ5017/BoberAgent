"""Synthetic E2→E3→E4 path through Router, neutral transport and retained bytes."""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts.runtime_preparation import (
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
    PreparationDispatchError,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import upgrade_database as upgrade_node
from boberagent_execution_node.persistence.orm import (
    PreparationAuthorityRow,
    PreparationMaterializationRow,
    RunRow,
)
from boberagent_execution_node.preparation.confinement import (
    E4_REQUIRED_FEATURES,
    ConfinementProof,
)
from boberagent_execution_node.preparation.service import NodePreparationService
from boberagent_transport import (
    InMemoryTransport,
    MaterializationRejected,
    MaterializeSourceRequest,
    materialization_message_id,
)
from test_runtime_preparation_e2 import NODE, _setup


class ControlledConfinement:
    """Test proof only; never represents Kali's production bubblewrap proof."""

    def preflight(self) -> ConfinementProof:
        return ConfinementProof("test-closed-proof", "1", E4_REQUIRED_FEATURES)


class IncompleteConfinement:
    def preflight(self) -> ConfinementProof:
        return ConfinementProof("test-incomplete", "1", ())


def test_e4_exact_source_publishes_reuses_and_reopens(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, _old, request = _setup(tmp_path)

    async def scenario() -> None:
        config = NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        node = ExecutionNode(config, preparation_confinement=ControlledConfinement())
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
            with pytest.raises(PreparationDispatchError, match="PREPARATION_STATE_INELIGIBLE"):
                await dispatch.materialize_source(admitted.attempt.preparation_ref)
            await dispatch.dispatch_and_import(admitted.attempt.preparation_ref, chunk_size=4096)
            wrong = MaterializeSourceRequest(
                message_id=materialization_message_id(admitted.permit.permit_ref),
                node_id=NODE,
                preparation_ref=admitted.attempt.preparation_ref,
                permit_ref=admitted.permit.permit_ref,
                permit_sha256="b" * 64,
                run_ref=admitted.permit.run_ref,
                timestamp=clock(),
            )
            rejected = await transport.exchange_preparation_materialization(wrong)
            assert isinstance(rejected, MaterializationRejected)
            assert rejected.code == "PREPARATION_AUTHORITY_MISMATCH"
            assert node.preparation is not None
            node.preparation._confinement = IncompleteConfinement()
            with pytest.raises(PreparationDispatchError, match="CONFINEMENT_UNAVAILABLE"):
                await dispatch.check_materialization(admitted.attempt.preparation_ref)
            node.preparation._confinement = ControlledConfinement()
            check = await dispatch.check_materialization(admitted.attempt.preparation_ref)
            assert (
                check.raw_artifact_ref == admitted.permit.spec.source.plan_source.raw_artifact_ref
            )
            assert node.database is not None
            with node.database.transaction() as session:
                assert (
                    session.get(
                        PreparationMaterializationRow, str(admitted.attempt.preparation_ref)
                    )
                    is None
                )
            evidence = await dispatch.materialize_source(admitted.attempt.preparation_ref)
            assert evidence.state == "PUBLISHED"
            assert evidence.file_count == 1
            assert evidence.materialized_bytes > 0
            assert evidence.verified_entry_count >= evidence.file_count
            assert evidence.observed_write_bytes == evidence.materialized_bytes
            assert evidence.observed_temporary_bytes == (
                admitted.permit.spec.source.plan_source.raw_size_bytes
                + admitted.permit.spec.source.manifest_size_bytes
                + evidence.materialized_bytes
            )
            assert evidence.budgets == admitted.permit.spec.budgets
            assert (
                evidence.raw_artifact_ref
                == admitted.permit.spec.source.plan_source.raw_artifact_ref
            )
            assert await dispatch.materialize_source(admitted.attempt.preparation_ref) == evidence
            assert node.database is not None
            with node.database.transaction() as session:
                row = session.get(
                    PreparationMaterializationRow, str(admitted.attempt.preparation_ref)
                )
                assert row is not None and row.state == "PUBLISHED"
            await node.shutdown()
            node = ExecutionNode(config, preparation_confinement=ControlledConfinement())
            await node.initialize()
            transport.register_node(ExecutionNodeTransportEndpoint(node), replace=True)
            assert await dispatch.materialize_source(admitted.attempt.preparation_ref) == evidence
            # A published directory is not trusted merely because the row says PUBLISHED.
            key = evidence.materialization_id.removeprefix("materialization:")
            published = config.workspace_root / "preparation-source" / "published" / key
            source_file = published / "checker.py"
            source_file.chmod(0o600)
            source_file.write_bytes(b"tampered")
            with pytest.raises(PreparationDispatchError, match="PREPARED_CONTENT_MISMATCH"):
                await dispatch.materialize_source(admitted.attempt.preparation_ref)
            assert node.database is not None
            with node.database.transaction() as session:
                row = session.get(
                    PreparationMaterializationRow, str(admitted.attempt.preparation_ref)
                )
                assert row is not None and row.state == "QUARANTINED"
            assert not published.exists()
        finally:
            await transport.disconnect()
            await node.shutdown()
            database.dispose()

    asyncio.run(scenario())


def test_incomplete_e4_restart_quarantines_owned_staging(tmp_path: Path) -> None:
    core, _plan, _policy, _approvals, _registry, service, request = _setup(tmp_path)
    admitted = service.admit(request)
    assert admitted.permit is not None
    permit = admitted.permit
    config = NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
    config.prepare_directories()
    database = RuntimeDatabase(config.database_path)
    upgrade_node(database)
    materialization_id = (
        "materialization:" + hashlib.sha256(str(permit.permit_ref).encode()).hexdigest()
    )
    key = materialization_id.removeprefix("materialization:")
    staging = config.workspace_root / "preparation-source" / "staging" / key
    staging.mkdir(parents=True)
    (staging / "partial.txt").write_text("incomplete")
    now = datetime.now(UTC)
    try:
        with database.transaction() as session:
            session.add(
                RunRow(
                    run_id=str(permit.run_ref),
                    mission_id=str(permit.spec.mission_ref),
                    capability_id="runtime.prepare",
                    operation="prepare",
                    status="QUEUED",
                    parent_run_id=None,
                    workflow_run_id=None,
                    invocation_fingerprint=None,
                    created_at=now,
                    started_at=None,
                    finished_at=None,
                    error_code=None,
                )
            )
            session.flush()
            session.add(
                PreparationAuthorityRow(
                    permit_id=str(permit.permit_ref),
                    preparation_id=str(permit.spec.preparation_ref),
                    run_id=str(permit.run_ref),
                    authority_sha256=preparation_permit_digest(permit),
                    principal_id="boberagent-core",
                    permit_json=permit.model_dump(mode="json"),
                    admitted_at=now,
                )
            )
            session.flush()
            session.add(
                PreparationMaterializationRow(
                    preparation_id=str(permit.spec.preparation_ref),
                    permit_id=str(permit.permit_ref),
                    run_id=str(permit.run_ref),
                    materialization_id=materialization_id,
                    state="INCOMPLETE",
                    evidence_json=None,
                    error_code=None,
                    started_at=now,
                    updated_at=now,
                )
            )
        NodePreparationService(
            database,
            config.imported_artifact_root,
            NODE,
            config.workspace_root,
            confinement=ControlledConfinement(),
        )
        with database.transaction() as session:
            row = session.get(PreparationMaterializationRow, str(permit.spec.preparation_ref))
            assert row is not None and row.state == "QUARANTINED"
            assert row.error_code == "PREPARATION_INTERRUPTED"
        assert not staging.exists()
        assert list((config.workspace_root / "preparation-source" / "quarantine").iterdir())
    finally:
        database.close()
        core.dispose()
