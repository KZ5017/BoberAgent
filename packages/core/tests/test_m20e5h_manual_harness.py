"""Portable H harness tests with explicit synthetic enforcement, NOT Kali acceptance."""

import argparse
import asyncio
import importlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from boberagent_contracts import DomainRef
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
    inventory,
)
from boberagent_execution_node.preparation.python_environment import PythonEnvironmentProvider
from boberagent_execution_node.preparation.python_provenance import validate_identity
from boberagent_execution_node.preparation.runtime_confinement_models import ProbeLimits
from boberagent_execution_node.preparation.runtime_confinement_store import ConfinementJournal
from boberagent_execution_node.preparation.runtime_service import NodePythonRuntimeService
from boberagent_execution_node.transport import NodeMcpArtifactSource
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpServerConfiguration,
    McpTransport,
    McpTransportServer,
)
from pydantic import BaseModel, SecretStr
from python_runtime_test_fixtures import runtime_binding_fixture
from test_python_provenance import configured as configured
from test_python_provenance import identity_probe
from test_python_revalidation_flow import GenerationBackend
from test_runtime_preparation_e4 import ControlledConfinement

ROOT = Path(__file__).resolve().parents[3]
NODE = "node-e5h-portable-not-host-acceptance"


@pytest.fixture
def smoke(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    directory = ROOT / "scripts/manual-smoke"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "e5h_manual_harness", directory / "m20e5h_acceptance_smoke_test.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def host_record(smoke: ModuleType, configured: PythonDistributionConfiguration) -> BaseModel:
    backend = runtime_binding_fixture().backend
    value = smoke.PreflightRecord(
        node_id=NODE,
        helper_sha256=backend.helper_sha256,
        bubblewrap_sha256=backend.binary_sha256,
        environment_helper_sha256="0" * 64,
        interpreter=validate_identity(inventory(configured), identity_probe()),
        kernel="synthetic-not-Linux-proof",
        profile="m20-e5-linux-bwrap-cgroup@1",
        delegation={},
        probes=[],
        node_configuration={},
    )
    assert isinstance(value, BaseModel)
    return value


def core_args(root: Path, host: Path, *, restart: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        core_runtime_directory=root,
        node_id=NODE,
        node_preflight=host,
        real_runtime_preparation=not restart,
        wait_seconds=10,
    )


def test_help_and_invalid_arguments(smoke: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        smoke.arguments(["--help"])
    assert result.value.code == 0
    assert "--restart-revalidation" in capsys.readouterr().out
    for args in (
        [],
        ["--check-config"],
        ["--real-runtime-preparation", "--wait-seconds", "0"],
        ["--node-report"],
    ):
        with pytest.raises(SystemExit) as failure:
            smoke.arguments(args)
        assert failure.value.code == 2


def test_fresh_root_and_records_never_repair_or_overwrite(
    smoke: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "fresh"
    smoke.fresh_directory(root)
    assert root.stat().st_mode & 0o777 == 0o700
    smoke.write_record(root, "record.json", {"result": "test-only"})
    assert (root / "record.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        smoke.write_record(root, "record.json", {"result": "overwrite denied"})
    root.chmod(0o775)
    with pytest.raises(FileExistsError):
        smoke.fresh_directory(root)
    assert root.stat().st_mode & 0o777 == 0o775


def test_missing_preflight_helper_fails_before_runtime_creation(
    smoke: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    configured: PythonDistributionConfiguration,
) -> None:
    from boberagent_execution_node.preparation.runtime_confinement_models import (
        RuntimeConfinementConfiguration,
    )

    root = tmp_path / "never-created"
    confinement = RuntimeConfinementConfiguration(
        delegated_parent=Path("/sys/fs/cgroup/absent"),
        helper_sha256="a" * 64,
        bubblewrap_sha256="b" * 64,
    )
    (tmp_path / "confinement.json").write_text(confinement.model_dump_json())
    # Missing/bad config must not initialize a Node, run a probe or create owned storage.
    (tmp_path / "distribution.json").write_text(configured.model_dump_json())
    assert (
        smoke.main(
            [
                "--check-config",
                "--node-runtime-directory",
                str(root),
                "--runtime-confinement-config",
                str(tmp_path / "confinement.json"),
                "--python-distribution-config",
                str(tmp_path / "distribution.json"),
                "--trusted-helper",
                str(tmp_path / "absent"),
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["reason"] == "CONFINEMENT_UNAVAILABLE"
    assert json.loads(output.out)["stage"] == "helper_file_mode"
    assert "Traceback" not in output.err and not root.exists()


def test_error_rendering_never_prints_transport_or_credential_payloads(
    smoke: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def bad_configuration(_args: object) -> None:
        raise ValueError("harmless-password-and-bearer-canary")

    monkeypatch.setattr(smoke, "configuration", bad_configuration)
    assert (
        smoke.main(
            [
                "--real-runtime-preparation",
                "--core-runtime-directory",
                str(tmp_path / "unused"),
                "--endpoint",
                "https://localhost:1/mcp",
                "--node-id",
                NODE,
                "--node-preflight",
                str(tmp_path / "missing.json"),
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert "canary" not in output.out + output.err
    assert json.loads(output.out)["execution_authorized"] is False
    assert "acquired_source_executed" not in json.loads(output.out)
    assert "preparation_terminal" not in json.loads(output.out)
    assert "Traceback" not in output.err


def test_wrong_node_and_restart_without_checkpoint_fail_closed(
    smoke: ModuleType, configured: PythonDistributionConfiguration, tmp_path: Path
) -> None:
    host = host_record(smoke, configured)
    smoke.write_record(tmp_path, "host.json", host)
    args = core_args(tmp_path / "not-created", tmp_path / "host.json")
    args.node_id = "wrong-node"
    with pytest.raises(smoke.AcceptanceFailure, match="NODE_PREFLIGHT_IDENTITY_CONFLICT"):
        smoke.CoreCase(args)
    assert not args.core_runtime_directory.exists()
    args.node_id, args.real_runtime_preparation = NODE, False
    with pytest.raises(smoke.AcceptanceFailure, match="EXISTING_H_CORE_REQUIRED"):
        smoke.CoreCase(args)


@pytest.mark.parametrize("fail_sync", [False, True])
def test_core_mcp_harness_first_restart_and_passive_audits(
    smoke: ModuleType,
    configured: PythonDistributionConfiguration,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_sync: bool,
) -> None:
    local = importlib.import_module("_m20e5h_node")

    host = host_record(smoke, configured)
    smoke.write_record(tmp_path, "host.json", host)
    args = core_args(tmp_path / "core", tmp_path / "host.json")
    case = smoke.CoreCase(args)  # actual synthetic C/D, outside running event loop
    configuration = NodeConfiguration.for_runtime_directory(
        tmp_path / "node", configured_node_id=NODE
    )
    backend = GenerationBackend((configured.distribution_root / "bin/python3.12").read_bytes())

    async def start_node() -> ExecutionNode:
        node = ExecutionNode(configuration, preparation_confinement=ControlledConfinement())
        await node.initialize()
        assert node.python_resources and node.python_environments and node.preparation
        backend.identity = backend.identity.model_copy(
            update={"boot_generation": node.python_resources._boot}
        )
        backend.proof_updates["boot_generation"] = node.python_resources._boot
        provider = PythonEnvironmentProvider(
            distribution=configured,
            backend=backend,
            backend_identity=runtime_binding_fixture().backend,
            repository=node.python_environments,
        )
        node.python_runtime_service = NodePythonRuntimeService(provider, node.preparation)
        return node

    async def run() -> None:
        node = await start_node()
        assert node.python_runtime_service
        server = None
        try:
            # Marker is a TEST FIXTURE, never proof that a Linux preflight ran here.
            test_host = host.model_copy(
                update={
                    "environment_helper_sha256": node.python_runtime_service.provider.helper_sha256
                }
            )
            smoke.write_record(configuration.runtime_directory, "e5h-preflight.json", test_host)
            for restart in (False, True):
                assert node.store
                server = McpTransportServer(
                    endpoint=ExecutionNodeTransportEndpoint(node),
                    artifact_source=NodeMcpArtifactSource(
                        store=node.store, spool_root=node.configuration.artifact_spool_root
                    ),
                    configuration=McpServerConfiguration(
                        port=0, bearer_token=SecretStr("harmless-h-fixture")
                    ),
                )
                await server.start()
                transport = McpTransport(
                    McpClientConfiguration(
                        endpoint_url=server.endpoint_url,
                        node_id=NODE,
                        bearer_token=SecretStr("harmless-h-fixture"),
                    )
                )
                current = (
                    case
                    if not restart
                    else smoke.CoreCase(core_args(case.root, tmp_path / "host.json", restart=True))
                )
                try:
                    if fail_sync:

                        async def sync_failure(_receiver: object) -> None:
                            raise ValueError("synthetic-sync-failure-canary")

                        monkeypatch.setattr(transport, "synchronize_artifacts", sync_failure)
                        with pytest.raises(ValueError, match="synthetic-sync-failure-canary"):
                            await current.run(transport)
                        assert not (case.root / "e5h-first.json").exists()
                        assert not (case.root / "e5h-first-validation-report.json").exists()
                        assert node.store and node.store.pending_results() == ()
                        return  # preserve the failed test's state, never resume/repair it
                    result = await current.run(transport)
                    assert result["result"] == "PASS" and result["preparation_terminal"] is False
                    assert result["core_reopened"] is restart
                finally:
                    current.database.dispose()
                assert node.python_resources and node.database
                if not restart:
                    # No actual restart must NOT be accepted as a fresh restart.
                    calls = tuple(backend.calls)
                    premature = smoke.CoreCase(
                        core_args(case.root, tmp_path / "host.json", restart=True)
                    )
                    try:
                        with pytest.raises(
                            smoke.AcceptanceFailure, match="UNEXPECTED_CURRENT_VALIDITY"
                        ):
                            await premature.run(
                                McpTransport(
                                    McpClientConfiguration(
                                        endpoint_url=server.endpoint_url,
                                        node_id=NODE,
                                        bearer_token=SecretStr("harmless-h-fixture"),
                                    )
                                )
                            )
                    finally:
                        premature.database.dispose()
                    assert tuple(backend.calls) == calls
                    # Simulate elapsed time through the existing injectable Core
                    # clock, never changing the immutable permit or DB history.
                    expired = smoke.CoreCase(
                        core_args(case.root, tmp_path / "host.json", restart=True)
                    )
                    expired_transport = McpTransport(
                        McpClientConfiguration(
                            endpoint_url=server.endpoint_url,
                            node_id=NODE,
                            bearer_token=SecretStr("harmless-h-fixture"),
                        )
                    )
                    expired.compose(expired_transport)
                    permit = expired.admission.get_permit(
                        expired.old.first.evidence.binding.request.permit_ref
                    )
                    expiry = permit.expires_at + timedelta(seconds=1)
                    expired.admission._clock = lambda instant=expiry: instant
                    expired.compose = lambda _carrier: None  # retain the injected clock
                    try:
                        with pytest.raises(
                            smoke.AcceptanceFailure, match="CURRENT_PREPARATION_AUTHORITY_REQUIRED"
                        ):
                            await expired.run(expired_transport)
                    finally:
                        expired.database.dispose()
                    assert tuple(backend.calls) == calls
                ref = result["runtime"]["resource_ref"]
                # Synthetic journal record tests READ-ONLY audit mechanics only.
                journal = ConfinementJournal(node.database)
                probe = identity_probe().model_copy(
                    update={"operation_id": DomainRef(f"h-fixture-{restart}")}
                )
                journal.begin(
                    probe.operation_id,
                    probe.probe,
                    ProbeLimits(),
                    probe.boot_generation,
                    "test-boot",
                    "0" * 64,
                    probe_timestamp := datetime.now(UTC),
                )
                journal.finish(probe, probe_timestamp)
                audit = argparse.Namespace(
                    node_runtime_directory=configuration.runtime_directory,
                    resource_ref=ref,
                    expected_runtime=case.root
                    / ("e5h-second.json" if restart else "e5h-first-runtime.json"),
                    stage="after-revalidation" if restart else "before-restart",
                )
                before_bytes = configuration.database_path.read_bytes()

                def forbidden_recovery(_self: object) -> None:
                    raise AssertionError("passive audit must never run startup recovery")

                with monkeypatch.context() as audit_guard:
                    audit_guard.setattr(
                        local.NodePreparationService,
                        "_recover_materializations",
                        forbidden_recovery,
                    )
                    inspected = local.node_report(audit)
                assert inspected["resource_count"] == 1
                assert configuration.database_path.read_bytes() == before_bytes
                await server.stop()
                server = None
                await node.shutdown()
                if not restart:
                    node = await start_node()
            source_file = next(
                (configuration.workspace_root / "preparation-source/published").rglob("checker.py")
            )
            source_file.chmod(0o644)
            source_file.write_bytes(b"# altered test fixture; never repair this evidence\n")
            before_bytes = configuration.database_path.read_bytes()
            with pytest.raises(ValueError):
                local.node_report(audit)
            assert configuration.database_path.read_bytes() == before_bytes
            assert (case.root / "e5h-restart-status.json").is_file()
            assert (
                json.loads((case.root / "e5h-restart-status.json").read_text())["current"][
                    "validity"
                ]
                == "UNCHECKED"
            )
        finally:
            if server:
                await server.stop()
            await node.shutdown()
            case.database.dispose()

    asyncio.run(run())


def test_bounded_record_reader_rejects_symlink_malformed_and_oversized(
    smoke: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "bad.json").write_text("not-json")
    with pytest.raises(ValueError):
        smoke.read_record(tmp_path / "bad.json", smoke.PreflightRecord)
    alias = tmp_path / "alias.json"
    alias.symlink_to(tmp_path / "bad.json")
    with pytest.raises(OSError):
        smoke.read_record(alias, smoke.PreflightRecord)
    (tmp_path / "large.json").write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(smoke.AcceptanceFailure, match="ACCEPTANCE_RECORD_TOO_LARGE"):
        smoke.read_record(tmp_path / "large.json", smoke.PreflightRecord)
