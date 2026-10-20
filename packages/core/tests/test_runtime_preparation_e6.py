"""Focused E6 completion, not E7 recovery matrix/E8/E9 or execution acceptance."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from boberagent_contracts import (
    CapabilityResult,
    CapabilityRunStatus,
    DomainRef,
    ExecutionPlan,
    ExecutionPlanStatus,
    IsolationRequirement,
    ResourceRef,
    RuntimePreparationInput,
    RuntimePreparationManifest,
    RuntimePreparationReceipt,
    preparation_permit_digest,
)
from boberagent_core.preparation import PreparationDispatchError
from boberagent_core.preparation.models import PreparationLifecycle
from boberagent_core.results import ResultIngestionService
from boberagent_core.results.errors import ConflictingResultError
from boberagent_execution_node.persistence.orm import ArtifactRow as NodeArtifactRow
from boberagent_execution_node.persistence.orm import ResultOutboxRow
from boberagent_execution_node.preparation.completion import NodePreparationCompletionService
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
)
from boberagent_execution_node.preparation.python_environment import EnvironmentFailure
from boberagent_execution_node.services.context_factory import LocalInvocationEnvironment
from boberagent_sdk import InvocationContext, MissionContext, PolicyDenied
from boberagent_transport import MaterializationEvidence, TransportMessageId
from e6_fixtures import E6Case
from sqlalchemy import select, text
from test_python_provenance import configured as configured


@pytest.mark.parametrize("artifact_first", [False, True])
def test_e6_normal_result_artifact_completion_reopen_and_lost_ack(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
    artifact_first: bool,
) -> None:
    case = E6Case(tmp_path, configured)

    async def scenario() -> None:
        try:
            await case.open()
            assert case.ready.evidence and case.node.store
            calls = tuple(case.backend.calls)
            admission = case.admission.current_admission(case.ref)
            assert admission is not None
            delivery = case.dispatch._delivery(admission)
            await case.finalize()
            result = case.node.store.get_result(case.permit.run_ref)
            assert result and result.execution_status is CapabilityRunStatus.COMPLETED, result
            assert result.outcome.category.value == "SUCCESS", result
            assert not (result.observations or result.effects or result.findings or result.sessions)
            assert len(result.artifacts) == 1
            raw = case.node.store.get_artifact(result.artifacts[0].artifact_id)
            assert raw
            manifest = RuntimePreparationManifest.model_validate_json(
                Path(raw.local_path).read_bytes()
            )
            assert manifest.materialization.file_count == case.source.file_count
            assert manifest.usage == case.ready.evidence.aggregate_usage
            assert manifest.usage.file_count > manifest.materialization.file_count
            assert manifest.resource_ref == case.ready.resource_ref
            assert manifest.environment.source_imported is False
            assert manifest.environment.entrypoint_executed is False
            assert manifest.external_installed_dependencies == ()
            assert not hasattr(manifest, "execution_authorization")
            assert tuple(case.backend.calls) == calls  # No construction/probes/source launch in E6.
            if artifact_first:
                assert all(o.synchronized for o in await case.coordinator().synchronize_pending())
            await case.deliver(acknowledge=False)
            attempt = case.completion.reconcile(case.ref)
            assert attempt.lifecycle is (
                PreparationLifecycle.COMPLETED
                if artifact_first
                else PreparationLifecycle.AWAITING_ARTIFACT
            )
            if not artifact_first:
                case.reopen_core()
                assert case.completion.get(case.ref).receipt == attempt.receipt
                assert all(o.synchronized for o in await case.coordinator().synchronize_pending())
            completed = case.completion.reconcile(case.ref)
            assert completed.lifecycle is PreparationLifecycle.COMPLETED
            assert completed.manifest == manifest
            assert (
                completed.completion_context
                and completed.completion_context.runtime.evidence == case.ready.evidence
            )
            await (
                case.deliver()
            )  # Lost ack → ordinary inbox/ingestion dedup, no semantic duplication.
            assert case.completion.reconcile(case.ref) == completed
            assert case.node.store.runtime_resource_count() == 1
            assert not case.node.store.pending_results()
            assert not case.node.store.list_processes_for_run(case.permit.run_ref)
            assert not case.node.store.list_sessions()
            assert (
                len(
                    [
                        a
                        for a in case.node.store.list_artifacts_for_run(case.permit.run_ref)
                        if a.descriptor.artifact_type == "runtime.preparation.manifest"
                    ]
                )
                == 1
            )
            # Same ordinary invocation replay cannot rebuild or emit a second manifest/result.
            await case.transport.submit_invocation(case.permit.spec.node_id, delivery)
            assert case.node.store.get_result(case.permit.run_ref) == result
            assert tuple(case.backend.calls) == calls
            case.reopen_core()
            assert case.completion.reconcile(case.ref) == completed
        finally:
            await case.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change", ["receipt", "binding", "missing_context", "conflict", "e5_artifact"]
)
def test_e6_rejects_receipt_binding_missing_authority_conflicts_and_e5_bytes(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
    change: str,
) -> None:
    case = E6Case(tmp_path, configured)

    async def scenario() -> None:
        try:
            await case.open()
            await case.finalize()
            assert case.node.store and case.node.database and case.ready.evidence
            result = case.node.store.get_result(case.permit.run_ref)
            assert result and result.outcome.category.value == "SUCCESS"
            if change in {"receipt", "binding"}:
                value = result.outcome.details["preparation_receipt"]
                assert isinstance(value, dict)
                receipt = dict(value)
                artifacts = result.artifacts
                if change == "receipt":
                    receipt["resource_ref"] = "resource-wrong"
                else:
                    artifacts = (
                        artifacts[0].model_copy(
                            update={
                                "metadata": {
                                    **artifacts[0].metadata,
                                    "binding_sha256": "0" * 64,
                                }
                            }
                        ),
                    )
                altered = result.model_copy(
                    update={
                        "artifacts": artifacts,
                        "outcome": result.outcome.model_copy(
                            update={"details": {"preparation_receipt": receipt}}
                        ),
                    }
                )
                with case.node.database.transaction() as session:
                    row = session.scalar(
                        select(ResultOutboxRow).where(
                            ResultOutboxRow.run_id == str(case.permit.run_ref)
                        )
                    )
                    assert row
                    row.result_json = altered.model_dump(mode="json")
                    spool = session.get(NodeArtifactRow, str(artifacts[0].artifact_id))
                    assert spool
                    spool.metadata_json = artifacts[0].metadata
            if change == "missing_context":
                with case.database._migration_engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE runtime_preparation_attempts SET completion_context_json = NULL WHERE preparation_id = :ref"
                        ),
                        {"ref": str(case.ref)},
                    )
            await case.deliver()
            assert all(o.synchronized for o in await case.coordinator().synchronize_pending())
            if change == "conflict":
                changed = result.model_copy(
                    update={
                        "outcome": result.outcome.model_copy(
                            update={"summary": "conflicting terminal claim"}
                        )
                    }
                )
                with pytest.raises(ConflictingResultError):
                    ResultIngestionService(case.database).accept_result(changed)
            if change == "e5_artifact":
                # Corrupt already synchronized evidence at rest. E6 rehashes independently.
                ref = case.ready.evidence.evidence_artifact_refs[0]
                with case.database.unit_of_work() as work:
                    key = work.artifacts.content_key(ref)
                assert key
                # Test-owned storage only; no production path bypasses M6.
                with case.storage.open_content(key) as stream:
                    path = Path(stream.name)
                path.write_bytes(b"corrupted retained E5 proof")
            failed = case.completion.reconcile(case.ref)
            assert failed.lifecycle is PreparationLifecycle.FAILED
            assert failed.completion_error_code == "PREPARATION_EVIDENCE_REJECTED"
            case.reopen_core()
            assert case.completion.reconcile(case.ref) == failed
            assert case.node.store.runtime_resource_count() == 1
        finally:
            await case.close()

    asyncio.run(scenario())


def test_e6_sync_failure_does_not_complete_or_redispatch(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
) -> None:
    case = E6Case(tmp_path, configured)

    async def scenario() -> None:
        try:
            await case.open()
            await case.finalize()
            assert case.node.store
            result = case.node.store.get_result(case.permit.run_ref)
            assert result
            ref = result.artifacts[0].artifact_id
            artifact = case.node.store.get_artifact(ref)
            assert artifact
            path = Path(artifact.local_path)
            original = path.read_bytes()
            path.write_bytes(b"x" * len(original))
            await case.deliver()
            outcome = await case.coordinator().synchronize(ref)
            assert not outcome.synchronized
            waiting = case.completion.reconcile(case.ref)
            assert waiting.lifecycle is PreparationLifecycle.AWAITING_ARTIFACT
            assert waiting.completion_error_code == "ARTIFACT_SYNC_FAILED"
            path.write_bytes(original)
            assert all(o.synchronized for o in await case.coordinator().synchronize_pending())
            assert case.completion.reconcile(case.ref).lifecycle is PreparationLifecycle.COMPLETED
            assert case.node.store.get_result(case.permit.run_ref) == result
        finally:
            await case.close()

    asyncio.run(scenario())


def test_e6_current_evidence_loss_cannot_emit_success(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = E6Case(tmp_path, configured)
    original = NodePreparationCompletionService.prepare_runtime

    async def lose_validity(
        self: NodePreparationCompletionService, request: RuntimePreparationInput
    ) -> RuntimePreparationReceipt:
        assert case.ready.resource_ref and case.node.python_resources
        case.node.python_resources.quarantine(case.ready.resource_ref, EnvironmentFailure().failure)
        return await original(self, request)

    monkeypatch.setattr(NodePreparationCompletionService, "prepare_runtime", lose_validity)

    async def scenario() -> None:
        try:
            await case.open()
            calls = tuple(case.backend.calls)
            await case.finalize()
            assert case.node.store
            result = case.node.store.get_result(case.permit.run_ref)
            assert result and result.execution_status is CapabilityRunStatus.FAILED
            assert result.outcome.category.value != "SUCCESS"
            assert result.artifacts == ()
            await case.deliver()
            assert case.completion.reconcile(case.ref).lifecycle is PreparationLifecycle.FAILED
            assert case.node.store.runtime_resource_count() == 1
            assert tuple(case.backend.calls) == calls
        finally:
            await case.close()

    asyncio.run(scenario())


def test_e6_early_finalization_cannot_start_source_materialization(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
) -> None:
    case = E6Case(tmp_path, configured)

    async def scenario() -> None:
        try:
            await case.open(build=False)  # E3 imports exist, but E4/E5 have not run.
            permit = case.permit
            raw = permit.spec.source.plan_source
            claim = MaterializationEvidence(
                request_message_id=TransportMessageId("transport-untrusted-claim"),
                node_id=permit.spec.node_id,
                preparation_ref=case.ref,
                permit_ref=permit.permit_ref,
                permit_sha256=preparation_permit_digest(permit),
                run_ref=permit.run_ref,
                mission_ref=permit.spec.mission_ref,
                plan_ref=permit.spec.plan_ref,
                plan_intent_sha256=permit.spec.plan_intent_sha256,
                raw_artifact_ref=raw.raw_artifact_ref,
                raw_sha256=raw.raw_sha256,
                manifest_artifact_ref=raw.manifest_artifact_ref,
                manifest_sha256=raw.manifest_sha256,
                materialization_id=DomainRef("materialization-claim"),
                file_count=1,
                verified_entry_count=1,
                materialized_bytes=1,
                observed_temporary_bytes=1,
                observed_write_bytes=1,
                observed_duration_seconds=0,
                budgets=permit.spec.budgets,
                tree_sha256="0" * 64,
                confinement_backend="not-evidence",
                confinement_version="1",
                proven_features=(),
                started_at=permit.issued_at,
                published_at=permit.issued_at,
            )
            with pytest.raises(PreparationDispatchError):
                await case.completion.finalize(
                    case.dispatch,
                    case.ref,
                    materialization=claim,
                    resource_ref=ResourceRef("resource-not-created"),
                    binding_sha256="0" * 64,
                )
            assert not (case.node.configuration.workspace_root / "preparation-source").exists()
            assert case.node.store and case.node.store.runtime_resource_count() == 0
            assert not case.node.store.pending_results()
            assert case.completion.get(case.ref).completion_context is None
            assert not case.backend.calls
        finally:
            await case.close()

    asyncio.run(scenario())


def test_e6_requires_current_valid_resource_and_execute_plan_stays_denied(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
) -> None:
    case = E6Case(tmp_path, configured)

    async def scenario() -> None:
        try:
            await case.open()
            assert case.node.python_resources and case.ready.resource_ref and case.node.runtime
            context = case.node.runtime._contexts.create(
                InvocationContext(
                    run_id=case.permit.run_ref,
                    capability_id="runtime.prepare",
                    operation="prepare",
                    mission_ref=case.permit.spec.mission_ref,
                ),
                LocalInvocationEnvironment(
                    mission=MissionContext(mission_ref=case.permit.spec.mission_ref)
                ),
            ).context
            with pytest.raises(PolicyDenied):
                await context.processes.execute_plan(
                    plan=ExecutionPlan(
                        execution_plan_id=case.permit.spec.plan_ref,
                        source_artifact_ref=case.permit.spec.source.plan_source.raw_artifact_ref,
                        status=ExecutionPlanStatus.VALIDATED,
                        runtime_type="python",
                        isolation=IsolationRequirement(profile="prepared"),
                        entrypoint="never-executed.py",
                        created_at=case.permit.not_before,
                    )
                )
            case.node.python_resources.quarantine(
                case.ready.resource_ref, EnvironmentFailure().failure
            )
            with pytest.raises((PreparationDispatchError, ValueError, EnvironmentFailure)):
                await case.finalize()
            assert case.node.store and not case.node.store.pending_results()
            assert case.completion.get(case.ref).completion_context is None
            run = case.node.store.get_run(case.permit.run_ref)
            assert run and run.status is CapabilityRunStatus.QUEUED
        finally:
            await case.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        "source_count",
        "aggregate_count",
        "materialized_bytes",
        "run",
        "preparation",
        "node",
        "provider",
        "profile",
        "resource",
        "permit",
        "source",
        "materialization",
        "digest",
        "corrupt",
    ],
)
def test_e6_rejects_manifest_not_matching_authoritative_e4_e5(
    tmp_path: Path,
    configured: PythonDistributionConfiguration,
    change: str,
) -> None:
    case = E6Case(tmp_path, configured)

    async def scenario() -> None:
        try:
            await case.open()
            await case.finalize()
            assert case.node.store
            result = case.node.store.get_result(case.permit.run_ref)
            assert result and result.outcome.category.value == "SUCCESS", result
            artifact = case.node.store.get_artifact(result.artifacts[0].artifact_id)
            assert artifact
            data = json.loads(Path(artifact.local_path).read_bytes())
            if change == "source_count":
                data["materialization"]["file_count"] += 1  # Still <= valid aggregate count.
            elif change == "aggregate_count":
                data["usage"]["file_count"] -= 1  # Still > source count, within admitted budget.
            elif change == "materialized_bytes":
                data["materialization"]["total_bytes"] += 1
                data["usage"]["materialized_bytes"] += 1  # Standalone Contract remains valid.
            elif change == "run":
                data["run_ref"] = "run-wrong"
            elif change == "preparation":
                data["spec"]["preparation_ref"] = "preparation-wrong"
            elif change == "node":
                data["spec"]["node_id"] = "node-wrong"
            elif change == "provider":
                data["spec"]["provider_version"] = "9.0.0"
            elif change == "profile":
                data["spec"]["profile_sha256"] = "0" * 64
            elif change == "resource":
                data["resource_ref"] = "resource-wrong"
            elif change == "permit":
                data["permit_ref"] = "permit-wrong"
            elif change == "source":
                data["spec"]["source"]["plan_source"]["raw_sha256"] = "0" * 64
            elif change == "materialization":
                data["materialization"]["tree_sha256"] = "0" * 64
            if change not in {"profile", "corrupt", "digest"}:
                RuntimePreparationManifest.model_validate(data)
            raw = b"not-json" if change == "corrupt" else json.dumps(data).encode()
            # Model a lying but internally well-formed authenticated sender. Transfer itself
            # verifies these bytes; Core must independently reject semantic identity/counts.
            descriptor = result.artifacts[0].model_copy(
                update={
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size_bytes": len(raw),
                }
            )
            receipt_value = result.outcome.details["preparation_receipt"]
            assert isinstance(receipt_value, dict)
            receipt = dict(receipt_value)
            receipt.update(
                manifest_sha256="0" * 64 if change == "digest" else descriptor.sha256,
                manifest_size_bytes=len(raw),
            )
            altered = CapabilityResult.model_validate(
                result.model_copy(
                    update={
                        "artifacts": (descriptor,),
                        "outcome": result.outcome.model_copy(
                            update={
                                "details": {"preparation_receipt": receipt},
                            }
                        ),
                    }
                ).model_dump()
            )
            from boberagent_execution_node.persistence.orm import ArtifactRow, ResultOutboxRow
            from sqlalchemy import select

            assert case.node.database
            with case.node.database.transaction() as session:
                row = session.get(ArtifactRow, str(descriptor.artifact_id))
                assert row
                assert descriptor.sha256 is not None
                row.sha256 = descriptor.sha256
                row.size_bytes = len(raw)
                out = session.scalar(
                    select(ResultOutboxRow).where(
                        ResultOutboxRow.run_id == str(case.permit.run_ref)
                    )
                )
                assert out
                out.result_json = altered.model_dump(mode="json")
            Path(artifact.local_path).write_bytes(raw)
            await case.deliver()
            assert all(o.synchronized for o in await case.coordinator().synchronize_pending())
            assert case.completion.reconcile(case.ref).lifecycle is PreparationLifecycle.FAILED
            assert case.node.store.runtime_resource_count() == 1
        finally:
            await case.close()

    asyncio.run(scenario())
