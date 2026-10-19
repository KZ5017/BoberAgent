"""G acceptance: production composition, never fake positive Linux evidence.

The positive case explicitly requires operator-provisioned host assets. Without
them portable CI proves composition/denial, not successful Linux enforcement.
No host provisioning, source execution or E6 completion is performed here.
"""

import asyncio
import builtins
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Never

import pytest
from boberagent_contracts import CapabilityRunStatus, DomainRef, RuntimePreparationRef
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    upgrade_database,
)
from boberagent_core.capabilities import CapabilityRegistrationClient
from boberagent_core.planning.approval import CorePlanApprovalService
from boberagent_core.planning.policy_service import CorePlanPolicyService
from boberagent_core.preparation import (
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
    PreparationDispatchError,
)
from boberagent_core.preparation.runtime import CorePythonRuntimeService
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.browser import BrowserRuntimeManager
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.listener import ListenerRuntimeManager
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
)
from boberagent_execution_node.preparation.resource_models import BudgetCategory
from boberagent_execution_node.preparation.runtime_confinement import LinuxRuntimeConfinementBackend
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ProbeEvidence,
    RuntimeConfinementConfiguration,
)
from boberagent_execution_node.preparation.service import PreparationAdmissionError
from boberagent_execution_node.processes.service import ManagedProcessService
from boberagent_execution_node.results import ResultOutbox
from boberagent_execution_node.services.context_factory import RunSecretService
from boberagent_transport import InMemoryTransport, MaterializationEvidence
from boberagent_transport.preparation_runtime import (
    PythonRuntimeAccepted,
    RuntimePreparationOperation,
)
from m20e5g_fixtures import MARKER, SOURCE_FILES, establish_d
from pydantic import BaseModel, ConfigDict


class HostConfiguration(BaseModel):
    """Explicit out-of-band operator assets; not a provider or authority fixture."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    confinement: RuntimeConfinementConfiguration
    distribution: PythonDistributionConfiguration
    helper: Path
    bubblewrap: Path


def clock() -> datetime:
    return datetime.now(UTC)


@pytest.fixture(autouse=True)
def no_generic_execution_secret_or_terminal_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("G crossed a forbidden execution/Secret/E6 boundary")

    for owner, name in (
        (ManagedProcessService, "run_tool"),
        (ManagedProcessService, "execute_plan"),
        (RunSecretService, "resolve"),
        (RunSecretService, "store"),
        (ResultOutbox, "persist_terminal"),
        (BrowserRuntimeManager, "create_resource"),
        (BrowserRuntimeManager, "create_session"),
        (ListenerRuntimeManager, "create_resource"),
    ):
        monkeypatch.setattr(owner, name, forbidden)


class Vertical:
    def __init__(self, root: Path, host: HostConfiguration | None = None) -> None:
        self.root, self.host = root, host
        self.database = CoreDatabase(DatabaseConfig.sqlite(root / "core.sqlite3"))
        upgrade_database(self.database)
        self.policy, self.request = establish_d(self.database, root, "node-e5g-synthetic")
        self.node_configuration = NodeConfiguration.for_runtime_directory(
            root / "node",
            configured_node_id=self.request.node_id,
            tools={}
            if host is None
            else {
                "runtime-confinement-helper": ToolConfiguration(executable=str(host.helper)),
                "runtime-confinement-bwrap": ToolConfiguration(executable=str(host.bubblewrap)),
            },
        )
        self.node = self.new_node()
        self.transport = InMemoryTransport(trusted_core_principal="boberagent-core")
        self.compose_core()

    def new_node(self) -> ExecutionNode:
        # The exact production constructor used by the Node CLI. No injected
        # confinement, replaced backend/provider, private worker calls or boot edits.
        return ExecutionNode(
            self.node_configuration,
            runtime_confinement_configuration=None if self.host is None else self.host.confinement,
            python_distribution_configuration=None if self.host is None else self.host.distribution,
        )

    def compose_core(self) -> None:
        self.registry = CapabilityRegistry(self.database, clock=clock)
        self.admission = CoreRuntimePreparationAdmissionService(
            self.database,
            self.policy,
            CorePlanApprovalService(self.database, self.policy, clock=clock),
            self.registry,
            clock=clock,
        )
        self.artifacts = CoreArtifactService(
            self.database,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=self.root / "artifacts")),
        )
        self.dispatch = CorePreparationDispatchService(
            self.database,
            self.admission,
            self.registry,
            CapabilityRouter(self.registry, self.transport, clock=clock),
            self.transport,
            self.artifacts,
            clock=clock,
        )
        self.runtime = CorePythonRuntimeService(self.dispatch)

    async def connect(self) -> None:
        await self.node.initialize()
        self.transport.register_node(ExecutionNodeTransportEndpoint(self.node))
        await self.transport.connect()
        await CapabilityRegistrationClient(self.transport, self.registry).refresh_node(
            self.request.node_id
        )

    async def close(self) -> None:
        await self.transport.disconnect()
        await self.node.shutdown()
        self.database.dispose()

    async def pump(
        self,
        ref: RuntimePreparationRef,
        source: MaterializationEvidence,
        operation: RuntimePreparationOperation,
        *,
        previous: PythonRuntimeAccepted | None = None,
        attempt: str,
    ) -> PythonRuntimeAccepted:
        deadline = asyncio.get_running_loop().time() + 350
        while True:
            response = await self.runtime.exchange(
                ref,
                materialization=source,
                operation=operation,
                attempt_id=DomainRef(attempt),
                resource_ref=None if previous is None else previous.resource_ref,
                binding_sha256=None
                if previous is None or previous.current is None
                else previous.current.binding_sha256,
            )
            if response.operation_state == "COMPLETED" and response.construction_sha256:
                return response
            assert response.operation_state not in {"FAILED", "INTERRUPTED"}, response
            assert asyncio.get_running_loop().time() < deadline, response
            await asyncio.sleep(0.05)

    def assert_nonterminal(self, ref: RuntimePreparationRef) -> None:
        attempt = self.admission.get_attempt(ref)
        assert attempt and attempt.lifecycle.value == "DISPATCHED"
        assert attempt.reserved_run_ref
        with self.database.unit_of_work() as work:
            run = work.runs.get(attempt.reserved_run_ref)
            assert run and run.status is CapabilityRunStatus.QUEUED
        assert self.node.store and self.node.store.pending_results() == ()
        assert self.node.store.list_sessions() == ()


def test_sentinel_fixture_has_no_hidden_install_or_execution_setup(tmp_path: Path) -> None:
    # Real C2/C3/D3/D4/D5 over the exact sentinel-bearing bytes, not fabricated D success.
    case = Vertical(tmp_path)
    try:
        with case.database.unit_of_work() as work:
            plan = work.execution_plans.get(case.request.plan_ref)
            assert plan is not None
        raw = case.artifacts.read_bytes(plan.plan.source.raw_artifact_ref)
        assert raw  # Fixtures retain ZIP bytes, never extract/execute them in Core.
        assert all(MARKER.encode() in data for data in SOURCE_FILES.values())
        assert "package/__init__.py" in SOURCE_FILES and "setup.py" in SOURCE_FILES
        assert "sitecustomize.py" in SOURCE_FILES
        assert case.node.python_runtime_service is None
        assert not case.node_configuration.workspace_root.exists()
    finally:
        case.database.dispose()


@pytest.mark.parametrize("boundary", ["unknown-preparation", "expired", "untrusted-peer"])
def test_portable_production_composition_fails_closed(tmp_path: Path, boundary: str) -> None:
    case = Vertical(tmp_path)

    async def run() -> None:
        try:
            await case.connect()
            assert case.node.python_runtime_service is None  # no configured assets / no fallback
            admitted = case.admission.admit(case.request)
            assert admitted.permit
            permit = admitted.permit
            ref = admitted.attempt.preparation_ref
            if boundary == "unknown-preparation":
                with pytest.raises(PreparationDispatchError, match="PREPARATION_NOT_FOUND"):
                    await case.dispatch.dispatch_and_import(
                        RuntimePreparationRef("preparation-missing")
                    )
            elif boundary == "expired":
                # Injectable Core clock, not mutation of the immutable permit/history.
                case.admission._clock = lambda: permit.expires_at + timedelta(seconds=1)
                with pytest.raises(PreparationDispatchError):
                    await case.dispatch.dispatch_and_import(ref)
            else:
                await case.transport.disconnect()
                case.transport = InMemoryTransport(trusted_core_principal="untrusted-peer")
                case.transport.register_node(ExecutionNodeTransportEndpoint(case.node))
                await case.transport.connect()
                case.compose_core()
                with pytest.raises(PreparationAdmissionError, match="CORE_PRINCIPAL_REQUIRED"):
                    await case.dispatch.dispatch_and_import(ref)
            assert not (case.node_configuration.workspace_root / "preparation-source").exists()
            assert not (case.node_configuration.workspace_root / "python-environments").exists()
            assert case.node.store and case.node.store.list_resources() == ()
            assert case.node.store.pending_results() == ()
        finally:
            await case.close()

    asyncio.run(run())


def test_configured_linux_backend_selected_without_positive_probe_fixture(tmp_path: Path) -> None:
    # Intentionally missing operator assets. Configuration selection is real;
    # absence can NEVER result in invented provenance/construction/readiness.
    host = HostConfiguration(
        confinement=RuntimeConfinementConfiguration(
            delegated_parent=Path("/sys/fs/cgroup/e5g-unconfigured"),
            helper_sha256="a" * 64,
            bubblewrap_sha256="b" * 64,
        ),
        distribution=PythonDistributionConfiguration(
            distribution_root=tmp_path / "missing-python",
            system_library_root=tmp_path / "missing-libraries",
            expected_manifest_sha256="c" * 64,
            expected_interpreter_sha256="d" * 64,
        ),
        helper=tmp_path / "missing-helper",
        bubblewrap=tmp_path / "missing-bwrap",
    )
    case = Vertical(tmp_path, host)

    async def run() -> None:
        try:
            await case.connect()
            backend = case.node.runtime_confinement
            service = case.node.python_runtime_service
            assert type(backend) is LinuxRuntimeConfinementBackend
            assert service and service.provider.backend is backend
            assert backend.configuration == host.confinement
            assert service.provider.distribution == host.distribution
            assert case.node.store and case.node.store.list_resources() == ()
            assert not (case.node_configuration.workspace_root / "python-environments").exists()
            admitted = case.admission.admit(case.request)
            assert admitted.permit
            ref = admitted.attempt.preparation_ref
            await case.dispatch.dispatch_and_import(ref)
            with pytest.raises(PreparationDispatchError, match="BACKEND_EXECUTABLE_UNAVAILABLE"):
                await case.dispatch.materialize_source(ref)
            assert case.node.store.list_resources() == ()
            assert not (case.node_configuration.workspace_root / "python-environments").exists()
            case.assert_nonterminal(ref)
        finally:
            await case.close()

    asyncio.run(run())


def test_opt_in_actual_linux_vertical_replay_reopen_revalidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = os.environ.get("BOBERAGENT_E5G_CONFIGURATION")
    if not path:
        pytest.skip("G production-positive acceptance needs explicit trusted host configuration")
    # Explicit opt-in bad config/prerequisites fail, never skip. This does not
    # discover/install/provision assets or use retained real acceptance runtimes.
    host = HostConfiguration.model_validate_json(Path(path).read_bytes())
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        assert name not in {"checker", "package", "setup", "sitecustomize", "pip", "ensurepip"}
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    case = Vertical(tmp_path, host)

    async def run() -> None:
        try:
            await case.connect()
            assert type(case.node.runtime_confinement) is LinuxRuntimeConfinementBackend
            assert case.node.python_runtime_service
            assert (
                case.node.python_runtime_service.provider.backend is case.node.runtime_confinement
            )
            admitted = case.admission.admit(case.request)
            assert admitted.permit
            permit, ref = admitted.permit, admitted.attempt.preparation_ref
            raw = permit.spec.source.plan_source
            original_bytes = {
                r: case.artifacts.read_bytes(r)
                for r in (raw.raw_artifact_ref, raw.manifest_artifact_ref)
            }
            imports = await case.dispatch.dispatch_and_import(ref, chunk_size=64)
            assert {item.artifact_ref for item in imports} == set(original_bytes)
            assert all(item.state.value == "VERIFIED" for item in imports)
            source = await case.dispatch.materialize_source(ref)
            assert source.preparation_ref == ref and source.run_ref == permit.run_ref
            assert source.raw_sha256 == raw.raw_sha256
            assert source.manifest_sha256 == raw.manifest_sha256
            # The published files are observed, not accessed through a provider
            # shortcut. No source is executed to prove these markers are inert.
            source_root = case.node_configuration.workspace_root / "preparation-source"
            snapshot = {
                str(path.relative_to(source_root)): (path.read_bytes(), path.stat().st_mode)
                for path in source_root.rglob("*")
                if path.is_file()
            }
            assert snapshot and all(not mode & 0o222 for _, mode in snapshot.values())
            assert not any("__pycache__" in name for name in snapshot)
            for data in SOURCE_FILES.values():
                assert any(content == data for content, _mode in snapshot.values())
            # Composed integrity failures must not start the first constructor.
            for bad_source in (
                source.model_copy(update={"tree_sha256": "0" * 64}),
                source.model_copy(update={"raw_sha256": "0" * 64}),
            ):
                with pytest.raises(PreparationDispatchError):
                    await case.runtime.exchange(
                        ref,
                        materialization=bad_source,
                        operation=RuntimePreparationOperation.PREPARE_RUNTIME,
                        attempt_id=DomainRef("g-bad-source"),
                    )
            assert case.node.store and case.node.store.list_resources() == ()
            prepared = await case.pump(
                ref, source, RuntimePreparationOperation.PREPARE_RUNTIME, attempt="g-prepare"
            )
            assert prepared.current and prepared.current.validity.value == "UNCHECKED"
            assert prepared.resource_ref and prepared.evidence
            resources = case.node.python_resources
            assert resources
            before = resources.budget(prepared.resource_ref)
            spent = {item.category: item.committed for item in before}
            assert spent[BudgetCategory.IMPORTED_BYTES] >= sum(map(len, original_bytes.values()))
            assert spent[BudgetCategory.MATERIALIZED_BYTES] >= source.materialized_bytes
            concurrent = await asyncio.gather(
                *(
                    case.pump(
                        ref,
                        source,
                        RuntimePreparationOperation.PREPARE_RUNTIME,
                        attempt="g-prepare",
                    )
                    for _ in range(2)
                )
            )
            assert all(item.resource_ref == prepared.resource_ref for item in concurrent)
            assert resources.budget(prepared.resource_ref) == before
            await case.transport.disconnect()
            await case.transport.connect()
            valid = await case.pump(
                ref,
                source,
                RuntimePreparationOperation.REVALIDATE_RUNTIME,
                previous=prepared,
                attempt="g-validate-1",
            )
            assert valid.current and valid.current.validity.value == "VALID"
            assert valid.current.state.value == "READY" and valid.current.phase.value == "PUBLISHED"
            assert valid.evidence and valid.evidence.environment
            binding = valid.evidence.binding
            assert binding.request.run_ref == permit.run_ref
            assert binding.request.spec == permit.spec
            assert binding.request.permit_ref == permit.permit_ref
            assert binding.request.materialization_id == source.materialization_id
            assert binding.request.source_tree_sha256 == source.tree_sha256
            balance = resources.budget(prepared.resource_ref)
            with pytest.raises(PreparationDispatchError):
                await case.runtime.exchange(
                    ref,
                    materialization=source,
                    operation=RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    resource_ref=valid.resource_ref,
                    binding_sha256="0" * 64,
                    attempt_id=DomainRef("g-binding-conflict"),
                )
            assert resources.budget(prepared.resource_ref) == balance
            replay = await case.pump(
                ref,
                source,
                RuntimePreparationOperation.REVALIDATE_RUNTIME,
                previous=valid,
                attempt="g-validate-1",
            )
            assert replay.evidence == valid.evidence
            assert resources.budget(prepared.resource_ref) == balance
            case.assert_nonterminal(ref)
            assert case.node.identity
            node_id = case.node.identity.node_id
            await case.close()
            case.database = CoreDatabase(case.database.config)
            case.policy = CorePlanPolicyService(case.database, case.policy._registry, clock=clock)
            case.node = case.new_node()
            case.transport = InMemoryTransport(trusted_core_principal="boberagent-core")
            case.compose_core()
            await case.connect()
            assert case.node.identity and case.node.identity.node_id == node_id
            status = await case.runtime.exchange(
                ref,
                materialization=source,
                operation=RuntimePreparationOperation.RUNTIME_STATUS,
                resource_ref=valid.resource_ref,
                binding_sha256=valid.current.binding_sha256,
            )
            assert status.current and status.current.validity.value == "UNCHECKED"
            assert status.evidence == valid.evidence
            assert status.construction_sha256 == valid.construction_sha256
            assert case.node.python_resources
            assert case.node.python_resources.budget(prepared.resource_ref) == balance
            fresh = await case.pump(
                ref,
                source,
                RuntimePreparationOperation.REVALIDATE_RUNTIME,
                previous=status,
                attempt="g-validate-2",
            )
            assert fresh.current and fresh.current.validity.value == "VALID"
            assert fresh.resource_ref == valid.resource_ref
            assert fresh.current.binding_sha256 == valid.current.binding_sha256
            assert fresh.construction_sha256 == valid.construction_sha256
            assert fresh.evidence and fresh.evidence != valid.evidence
            assert fresh.evidence.environment == valid.evidence.environment
            assert fresh.operation_id != valid.operation_id
            assert len(case.node.store.list_resources()) == 1 if case.node.store else False
            assert await case.dispatch.materialize_source(ref) == source
            assert {
                str(path.relative_to(source_root)): (path.read_bytes(), path.stat().st_mode)
                for path in source_root.rglob("*")
                if path.is_file()
            } == snapshot
            newer_balance = case.node.python_resources.budget(prepared.resource_ref)
            old_spent = {item.category: item.committed for item in balance}
            assert all(item.committed >= old_spent[item.category] for item in newer_balance)
            assert any(item.committed > old_spent[item.category] for item in newer_balance)
            for artifact_ref, data in original_bytes.items():
                assert case.artifacts.read_bytes(artifact_ref) == data
            case.assert_nonterminal(ref)
            # Read-only final checks: markers cannot hide in captured trusted output.
            evidence_json = fresh.evidence.model_dump_json()
            assert MARKER not in evidence_json
            # Native output is hex-encoded in the durable journal, not necessarily
            # carried in shared evidence. Inspect that history read-only as well.
            with sqlite3.connect(
                case.node_configuration.database_path.as_uri() + "?mode=ro", uri=True
            ) as journal:
                rows = journal.execute(
                    "SELECT evidence_json FROM runtime_confinement_operations"
                ).fetchall()
            assert rows and all(row[0] is not None for row in rows)
            for (encoded,) in rows:
                proof = ProbeEvidence.model_validate_json(encoded)
                assert MARKER.encode() not in bytes.fromhex(proof.stdout_hex)
                assert MARKER.encode() not in bytes.fromhex(proof.stderr_hex)
            assert fresh.evidence.non_actions.target_secret_grants == ()
            assert fresh.evidence.non_actions.preparation_network == "NONE"
            assert fresh.evidence.non_actions.source_imported is False
            assert fresh.evidence.non_actions.entrypoint_executed is False
            assert fresh.evidence.non_actions.package_installed is False
        finally:
            await case.close()

    asyncio.run(run())
