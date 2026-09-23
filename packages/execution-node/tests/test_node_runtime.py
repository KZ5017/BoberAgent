"""Local Capability Runtime integration tests with production Node services."""

import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    AssetRef,
    CapabilityInvocation,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    CapabilityRunStatus,
    DependencyDeclaration,
    DependencyType,
    MissionRef,
    SecretRef,
    WorkflowRunRef,
)
from boberagent_execution_node import (
    ExecutionNode,
    LocalInvocationEnvironment,
    NodeConfiguration,
    NodeLifecycleState,
    ToolConfiguration,
)
from boberagent_execution_node.artifacts import LocalArtifactSpool
from boberagent_execution_node.persistence import (
    ArtifactSyncState,
    ProcessRecord,
    ProcessState,
    RunRecord,
)
from boberagent_execution_node_test_capabilities import capability_manifest
from boberagent_sdk import AssetSnapshot, MissionContext, UtcClock
from boberagent_transport import SecretGrant

MISSION_REF = MissionRef("mission-node-tests")
ASSET_REF = AssetRef("asset-node-tests")


def _python_dependency() -> tuple[DependencyDeclaration, ...]:
    return (
        DependencyDeclaration(
            dependency_type=DependencyType.TOOL,
            identifier="python",
            version_spec=">=3.12",
        ),
    )


def _write_manifest(
    root: Path,
    *,
    capability_id: str = "test.synthetic_runtime",
    implementation: str = ("boberagent_execution_node_test_capabilities:SyntheticCapability"),
    dependencies: tuple[DependencyDeclaration, ...] | None = None,
    operations: tuple[str, ...] = ("run", "sleep"),
    input_model: str = "boberagent_execution_node_test_capabilities:SyntheticInput",
) -> None:
    root.mkdir(parents=True)
    manifest = capability_manifest(
        capability_id=capability_id,
        implementation=implementation,
        dependencies=_python_dependency() if dependencies is None else dependencies,
        operations=operations,
        input_model=input_model,
    )
    (root / "capability.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _configuration(
    runtime_root: Path,
    capability_root: Path,
    *,
    max_inline_output_bytes: int = 1024 * 1024,
) -> NodeConfiguration:
    base = NodeConfiguration.for_runtime_directory(
        runtime_root,
        capability_paths=(capability_root,),
        tools={
            "python": ToolConfiguration(
                executable=sys.executable,
                version_args=("--version",),
            )
        },
    )
    return base.model_copy(update={"max_inline_process_output_bytes": max_inline_output_bytes})


def _invocation(
    run_ref: str,
    *,
    operation: str = "run",
    capability_id: str = "test.synthetic_runtime",
    timeout: float = 5,
    message: str = "literal ; $(not-a-shell) value",
    parent_run_ref: CapabilityRunRef | None = None,
    workflow_run_ref: WorkflowRunRef | None = None,
) -> CapabilityInvocation:
    return CapabilityInvocation(
        run_id=CapabilityRunRef(run_ref),
        capability_id=capability_id,
        operation=operation,
        mission_ref=MISSION_REF,
        parent_run_ref=parent_run_ref,
        workflow_run_ref=workflow_run_ref,
        inputs={
            "asset_ref": str(ASSET_REF),
            "message": message,
            "timeout": timeout,
        },
    )


def _environment() -> LocalInvocationEnvironment:
    asset = AssetSnapshot(ref=ASSET_REF, primary_address="192.0.2.25")
    return LocalInvocationEnvironment(
        mission=MissionContext(mission_ref=MISSION_REF, name="Node tests"),
        allowed_assets=frozenset({ASSET_REF}),
        allowed_addresses=frozenset({asset.primary_address}),
        entities=(asset,),
    )


def test_synthetic_capability_runtime_persists_and_replays_after_restart(
    tmp_path: Path,
) -> None:
    capability_root = tmp_path / "capabilities"
    runtime_root = tmp_path / "runtime"
    _write_manifest(capability_root)
    configuration = _configuration(runtime_root, capability_root)
    invocation = _invocation(
        "run-synthetic-restart",
        parent_run_ref=CapabilityRunRef("run-parent"),
        workflow_run_ref=WorkflowRunRef("workflow-node-tests"),
    )

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        health = await node.initialize()
        assert health.lifecycle is NodeLifecycleState.READY
        identity = health.node_id

        result = await node.execute_local(invocation, _environment())
        assert result.execution_status is CapabilityRunStatus.COMPLETED
        assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
        assert result.observations[0].value == {
            "message": "literal ; $(not-a-shell) value",
            "address": "192.0.2.25",
            "stdout": "literal ; $(not-a-shell) value\n",
            "stderr": "synthetic-stderr\n",
        }
        assert result.observations[0].evidence_refs == (result.artifacts[0].artifact_id,)
        assert node.store is not None
        run = node.store.get_run(invocation.run_id)
        assert run is not None and run.status is CapabilityRunStatus.COMPLETED
        assert run.parent_run_ref == invocation.parent_run_ref
        assert run.workflow_run_ref == invocation.workflow_run_ref
        processes = node.store.list_processes_for_run(invocation.run_id)
        assert len(processes) == 1
        assert processes[0].state is ProcessState.EXITED
        assert processes[0].exit_code == 0
        assert processes[0].argument_count == 3
        assert len(node.store.list_workspaces_for_owner(str(invocation.run_id))) == 1
        artifact_record = node.store.get_artifact(result.artifacts[0].artifact_id)
        assert artifact_record is not None
        assert artifact_record.sync_state is ArtifactSyncState.LOCAL_ONLY
        assert Path(artifact_record.local_path).read_bytes() == (
            b"literal ; $(not-a-shell) value\n"
        )
        assert len(node.store.pending_results()) == 1
        assert len(node.store.pending_events()) == 3
        await node.shutdown()
        stopped_health = node.health()
        assert stopped_health.lifecycle is NodeLifecycleState.OFFLINE
        assert not stopped_health.database_ready

        reopened = ExecutionNode(configuration)
        reopened_health = await reopened.initialize()
        assert reopened_health.node_id == identity
        assert reopened.store is not None
        assert len(reopened.store.pending_results()) == 1
        assert len(reopened.store.pending_events()) == 3
        replayed = await reopened.execute_local(invocation, _environment())
        assert replayed == result
        assert len(reopened.store.list_processes_for_run(invocation.run_id)) == 1

        spool = LocalArtifactSpool(
            root=configuration.artifact_spool_root,
            allowed_source_roots=(configuration.workspace_root,),
            store=reopened.store,
            run_ref=invocation.run_id,
            clock=UtcClock().now,
        )
        assert await spool.get(result.artifacts[0].artifact_id) == result.artifacts[0]
        assert await spool.read_bytes(result.artifacts[0].artifact_id) == (
            b"literal ; $(not-a-shell) value\n"
        )

        pending_event = reopened.store.pending_events()[0]
        assert reopened.events is not None
        reopened.events.enqueue(pending_event.event)
        assert len(reopened.store.pending_events()) == 3
        reopened.events.mark_delivered(pending_event.sequence)
        assert len(reopened.store.pending_events()) == 2
        assert reopened.results is not None
        pending_result = reopened.results.pending()[0]
        reopened.results.mark_delivered(pending_result.sequence)
        assert not reopened.results.pending()
        await reopened.shutdown()

    asyncio.run(scenario())


def test_authorized_secret_resolution_and_logging_redaction(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capability_root = tmp_path / "capabilities"
    _write_manifest(
        capability_root,
        capability_id="test.secret_consumer",
        implementation=("boberagent_execution_node_test_capabilities:SecretConsumerCapability"),
        dependencies=(),
        operations=("verify",),
        input_model=("boberagent_execution_node_test_capabilities:SecretConsumerInput"),
    )
    configuration = _configuration(tmp_path / "runtime", capability_root)
    plaintext = b"harmless-test-password"
    secret_ref = SecretRef("secret-node-test")
    invocation = CapabilityInvocation(
        run_id=CapabilityRunRef("run-secret-consumer"),
        capability_id="test.secret_consumer",
        operation="verify",
        mission_ref=MISSION_REF,
        inputs={
            "secret_ref": str(secret_ref),
            "expected_sha256": hashlib.sha256(plaintext).hexdigest(),
        },
    )
    environment = LocalInvocationEnvironment(
        mission=MissionContext(mission_ref=MISSION_REF),
        secret_grants=(
            SecretGrant(
                secret_ref=secret_ref,
                value=plaintext,
                authorized_purpose="test.secret_consumer:verify",
            ),
        ),
    )

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        result = await node.execute_local(invocation, environment)
        assert result.execution_status is CapabilityRunStatus.COMPLETED
        assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
        assert plaintext.decode() not in result.model_dump_json()
        await node.shutdown()

    with caplog.at_level("INFO", logger="boberagent.execution_node.capability"):
        asyncio.run(scenario())
    assert plaintext.decode() not in caplog.text
    assert "<REDACTED>" in caplog.text
    assert str(secret_ref) in caplog.text


def test_large_process_output_spills_to_artifact(tmp_path: Path) -> None:
    capability_root = tmp_path / "capabilities"
    _write_manifest(capability_root)
    configuration = _configuration(tmp_path / "runtime", capability_root, max_inline_output_bytes=8)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        invocation = _invocation("run-output-spill", message="long-output-value")
        result = await node.execute_local(invocation, _environment())
        assert result.execution_status is CapabilityRunStatus.COMPLETED
        assert node.store is not None
        artifacts = node.store.list_artifacts_for_run(invocation.run_id)
        assert {record.descriptor.artifact_type for record in artifacts} == {
            "process.stdout",
            "process.stderr",
            "test.synthetic_output",
        }
        assert not tuple(configuration.process_output_root.iterdir())
        await node.shutdown()

    asyncio.run(scenario())


def test_missing_dependency_fails_before_provider_import(tmp_path: Path) -> None:
    capability_root = tmp_path / "capabilities"
    missing_dependency = (
        DependencyDeclaration(
            dependency_type=DependencyType.TOOL,
            identifier="not-installed",
        ),
    )
    _write_manifest(
        capability_root,
        capability_id="test.missing_dependency",
        implementation="this_module_must_not_be_imported:Capability",
        dependencies=missing_dependency,
    )
    configuration = _configuration(tmp_path / "runtime", capability_root)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        health = await node.initialize()
        assert health.lifecycle is NodeLifecycleState.DEGRADED
        result = await node.execute_local(
            _invocation("run-missing-dependency", capability_id="test.missing_dependency"),
            _environment(),
        )
        assert result.execution_status is CapabilityRunStatus.FAILED
        assert result.diagnostics[0].code == "DEPENDENCY_UNAVAILABLE"
        assert node.capabilities.get("test.missing_dependency").failure is None
        await node.shutdown()

    asyncio.run(scenario())


def test_invalid_capability_result_is_contained_as_valid_failure(tmp_path: Path) -> None:
    capability_root = tmp_path / "capabilities"
    _write_manifest(
        capability_root,
        capability_id="test.invalid_result",
        implementation=("boberagent_execution_node_test_capabilities:InvalidResultCapability"),
    )
    configuration = _configuration(tmp_path / "runtime", capability_root)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        invocation = _invocation("run-invalid-result", capability_id="test.invalid_result")
        result = await node.execute_local(invocation, _environment())
        assert result.execution_status is CapabilityRunStatus.FAILED
        assert result.diagnostics[0].code == "IMPLEMENTATION_INVALID"
        assert node.results is not None
        assert node.results.get(invocation.run_id) == result
        await node.shutdown()

    asyncio.run(scenario())


def test_local_scope_projection_fails_closed_before_process_start(tmp_path: Path) -> None:
    capability_root = tmp_path / "capabilities"
    _write_manifest(capability_root)
    configuration = _configuration(tmp_path / "runtime", capability_root)

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        invocation = _invocation("run-scope-denied")
        asset = AssetSnapshot(ref=ASSET_REF, primary_address="192.0.2.25")
        denied_environment = LocalInvocationEnvironment(
            mission=MissionContext(mission_ref=MISSION_REF),
            entities=(asset,),
        )
        result = await node.execute_local(invocation, denied_environment)
        assert result.execution_status is CapabilityRunStatus.FAILED
        assert result.diagnostics[0].code == "SCOPE_VIOLATION"
        assert node.store is not None
        assert not node.store.list_processes_for_run(invocation.run_id)
        await node.shutdown()

    asyncio.run(scenario())


def test_real_process_timeout_and_cancellation_update_local_state(tmp_path: Path) -> None:
    capability_root = tmp_path / "capabilities"
    _write_manifest(capability_root)
    configuration = _configuration(tmp_path / "runtime", capability_root)

    async def wait_for_process(node: ExecutionNode, run_ref: CapabilityRunRef) -> ProcessRecord:
        for _ in range(300):
            assert node.store is not None
            processes = node.store.list_processes_for_run(run_ref)
            if processes and processes[0].state is ProcessState.RUNNING:
                return processes[0]
            await asyncio.sleep(0.01)
        raise AssertionError("managed process did not enter RUNNING")

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()

        timed_out_invocation = _invocation("run-process-timeout", operation="sleep", timeout=0.05)
        timed_out = await node.execute_local(timed_out_invocation, _environment())
        assert timed_out.execution_status is CapabilityRunStatus.TIMED_OUT
        assert node.store is not None
        timeout_process = node.store.list_processes_for_run(timed_out_invocation.run_id)[0]
        assert timeout_process.state is ProcessState.TIMED_OUT

        cancelled_invocation = _invocation("run-process-cancel", operation="sleep", timeout=10)
        task = asyncio.create_task(node.execute_local(cancelled_invocation, _environment()))
        running = await wait_for_process(node, cancelled_invocation.run_id)
        assert running.pid is not None
        assert node.runtime is not None
        assert node.runtime.cancel(str(cancelled_invocation.run_id))
        cancelled = await task
        assert cancelled.execution_status is CapabilityRunStatus.CANCELLED
        cancelled_process = node.store.list_processes_for_run(cancelled_invocation.run_id)[0]
        assert cancelled_process.state is ProcessState.CANCELLED
        assert cancelled_process.pid == running.pid
        with pytest.raises(ProcessLookupError):
            os.kill(running.pid, 0)
        run = node.store.get_run(cancelled_invocation.run_id)
        assert run is not None and run.status is CapabilityRunStatus.CANCELLED
        await node.shutdown()

    asyncio.run(scenario())


def test_restart_conservatively_recovers_running_run_and_process(tmp_path: Path) -> None:
    capability_root = tmp_path / "capabilities"
    capability_root.mkdir()
    configuration = _configuration(tmp_path / "runtime", capability_root)
    run_ref = CapabilityRunRef("run-interrupted")

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        first_health = await node.initialize()
        assert node.store is not None
        node.store.add_run(
            RunRecord(
                run_ref=run_ref,
                mission_ref=MISSION_REF,
                capability_id="test.interrupted",
                operation="run",
                status=CapabilityRunStatus.RUNNING,
                created_at=datetime(2026, 9, 17, tzinfo=UTC),
                started_at=datetime(2026, 9, 17, tzinfo=UTC),
            )
        )
        node.store.add_process(
            ProcessRecord(
                process_id="process-interrupted",
                run_ref=run_ref,
                tool="python",
                state=ProcessState.RUNNING,
                argument_count=1,
                pid=999_999,
                started_at=datetime(2026, 9, 17, tzinfo=UTC),
            )
        )
        await node.shutdown()

        reopened = ExecutionNode(configuration)
        health = await reopened.initialize()
        assert health.node_id == first_health.node_id
        assert health.lifecycle is NodeLifecycleState.DEGRADED
        assert reopened.store is not None
        run = reopened.store.get_run(run_ref)
        assert run is not None
        assert run.status is CapabilityRunStatus.FAILED
        assert run.error_code == "INTERRUPTED_EXECUTION_STATE_UNKNOWN"
        process = reopened.store.get_process("process-interrupted")
        assert process is not None and process.state is ProcessState.LOST
        result = reopened.store.get_result(run_ref)
        assert result is not None
        assert result.execution_status is CapabilityRunStatus.FAILED
        assert result.outcome.category is CapabilityOutcomeCategory.UNKNOWN
        await reopened.shutdown()

    asyncio.run(scenario())
