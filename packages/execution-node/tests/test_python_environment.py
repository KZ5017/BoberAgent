"""E5-E durable wiring with synthetic bytes/proofs; not real Kali acceptance."""

import asyncio
import hashlib
import json
import struct
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from boberagent_contracts import (
    DomainRef,
    PythonProviderOperation,
    PythonProviderPhase,
    PythonResourceState,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeValidity,
    preparation_permit_digest,
    preparation_spec_fingerprint,
)
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import current_revision, upgrade_database
from boberagent_execution_node.persistence.orm import (
    PythonEnvironmentRow,
    PythonResourceRow,
    RuntimeResourceRow,
)
from boberagent_execution_node.preparation.environment_models import (
    EmptyEnvironmentEvidence,
    EnvironmentEntry,
    EnvironmentIdentity,
    EnvironmentManifest,
)
from boberagent_execution_node.preparation.environment_storage import (
    DIRECTORIES,
    EXECUTABLES,
    FILES,
    EnvironmentStorage,
)
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
    inventory,
)
from boberagent_execution_node.preparation.python_environment import (
    EnvironmentFailure,
    PythonEnvironmentProvider,
    PythonEnvironmentRepository,
)
from boberagent_execution_node.preparation.python_provenance import (
    PythonProvenanceRepository,
    inspect_owned_interpreter,
)
from boberagent_execution_node.preparation.resource_models import (
    BudgetAmount,
    BudgetCategory,
    OperationState,
    ResourceOperation,
)
from boberagent_execution_node.preparation.resources import (
    PythonResourceRepository,
    ResourceOwnershipError,
)
from boberagent_execution_node.preparation.runtime_confinement import RuntimeConfinementUnavailable
from boberagent_execution_node.preparation.runtime_confinement_models import (
    EnvironmentLimits,
    ProbeEvidence,
    TrustedPythonOperation,
)
from plan_test_fixtures import NOW
from python_runtime_test_fixtures import runtime_authority_fixture, runtime_binding_fixture
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_python_provenance import FakeIdentityBackend, identity_probe, repin
from test_python_provenance import configured as configured
from test_python_resource_ownership import _seed


def export_fixture(binary: bytes) -> tuple[EnvironmentManifest, bytes]:
    config = b"home = /runtime/bin\ninclude-system-site-packages = false\nversion = 3.12.14\nexecutable = /runtime/bin/python3.12\ncommand = /runtime/bin/python3.12 -m venv --copies --without-pip /work/venv\n"
    files = {
        path: binary
        if path in EXECUTABLES
        else config
        if path == "pyvenv.cfg"
        else b"# inert activation fixture\n"
        for path in FILES
    }
    entries = [
        EnvironmentEntry(path=path, kind="directory", mode=0o755, size=0) for path in DIRECTORIES
    ]
    entries.extend(
        EnvironmentEntry(
            path=path,
            kind="file",
            mode=0o755 if path in EXECUTABLES else 0o644,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for path, data in files.items()
    )
    entries.append(EnvironmentEntry(path="lib64", kind="symlink", mode=0o777, size=0, target="lib"))
    manifest = EnvironmentManifest(
        entries=tuple(sorted(entries, key=lambda e: e.path)),
        written_bytes=sum(map(len, files.values())),
        created_entries=len(entries),
    )
    header = manifest.model_dump_json().encode()
    data = (
        struct.pack("!I", len(header))
        + header
        + b"".join(files[e.path] for e in manifest.entries if e.kind == "file")
    )
    return manifest, data


class FakeEnvironmentBackend(FakeIdentityBackend):
    def __init__(self, binary: bytes) -> None:
        super().__init__()
        self.manifest, self.export = export_fixture(binary)
        self.failure: str | None = None
        self.proof_updates: dict[str, object] = {}
        self.identity_updates: dict[str, object] = {}

    async def run_environment_create(
        self,
        distribution: PythonDistributionConfiguration,
        operation_id: DomainRef,
        export_path: Path,
        helper_sha256: str,
        *,
        cancellation: object = None,
    ) -> ProbeEvidence:
        self.calls.append("create")
        if self.failure == "cancel":
            raise asyncio.CancelledError()
        if self.failure == "create":
            raise RuntimeConfinementUnavailable()
        export_path.write_bytes(self.export)
        output = json.dumps(
            dict(
                written_bytes=self.manifest.written_bytes,
                created_entries=self.manifest.created_entries,
                export_bytes=len(self.export),
            )
        )
        return identity_probe().model_copy(
            update=dict(
                operation_id=operation_id,
                probe=TrustedPythonOperation.CREATE_ENVIRONMENT,
                limits=EnvironmentLimits(),
                stdout_hex=output.encode().hex(),
                **self.proof_updates,
            )
        )

    async def run_environment_verify(
        self,
        distribution: PythonDistributionConfiguration,
        operation_id: DomainRef,
        environment_path: Path,
        helper_sha256: str,
        *,
        cancellation: object = None,
    ) -> ProbeEvidence:
        self.calls.append("verify")
        if self.failure == "verify":
            raise RuntimeConfinementUnavailable()
        identity = dict(
            implementation="cpython",
            version="3.12.14",
            platform="linux",
            architecture="x86_64",
            cache_tag="cpython-312",
            soabi="cpython-312-x86_64-linux-gnu",
            prefix="/work/venv",
            base_prefix="/runtime",
            executable="/work/venv/bin/python3.12",
            paths=[
                "/runtime/lib/python312.zip",
                "/runtime/lib/python3.12",
                "/runtime/lib/python3.12/lib-dynload",
                "/work/venv/lib/python3.12/site-packages",
            ],
            isolated=1,
            no_site=0,
            no_bytecode=True,
            user_site=False,
            written_bytes=0,
            created_entries=0,
        )
        identity.update(self.identity_updates)
        return identity_probe().model_copy(
            update=dict(
                operation_id=operation_id,
                probe=TrustedPythonOperation.VERIFY_ENVIRONMENT,
                limits=EnvironmentLimits(),
                stdout_hex=json.dumps(identity).encode().hex(),
            )
        )


class Case:
    def __init__(
        self,
        database: RuntimeDatabase,
        resources: PythonResourceRepository,
        repository: PythonEnvironmentRepository,
        provider: PythonEnvironmentProvider,
        backend: FakeEnvironmentBackend,
        claim: ResourceOperation,
    ) -> None:
        self.database, self.resources, self.repository = database, resources, repository
        self.provider, self.backend, self.claim = provider, backend, claim

    def create(self) -> EmptyEnvironmentEvidence:
        return asyncio.run(self.provider.create_empty_environment(self.claim))

    @property
    def path(self) -> Path:
        return self.repository.storage.resource_directory(self.claim.resource_ref)


@pytest.fixture
def case(
    configured: PythonDistributionConfiguration, tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[Case]:
    hook: object = getattr(request, "param", None)
    if hook is not None:
        assert isinstance(hook, str)
        path = configured.distribution_root / "lib/python3.12" / hook
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"raise RuntimeError('startup hook must never execute')\n")
        path.chmod(0o644)
        configured = repin(configured)  # D intentionally permits -S static/provenance proof.
    database = RuntimeDatabase(tmp_path / "environment.sqlite3")
    upgrade_database(database, "0010_python_provenance")
    authority = runtime_authority_fixture()
    budgets = authority.permit.spec.budgets.model_copy(
        update=dict(
            max_file_count=15000,
            max_processes=11,
            max_total_runtime_seconds=1200,
            max_process_runtime_seconds=60,
            max_memory_bytes=256 * 1024**2,
            max_temporary_bytes=160 * 1024**2,
            max_preparation_write_bytes=256 * 1024**2,
            max_captured_output_bytes=200000,
        )
    )
    spec = authority.permit.spec.model_copy(update={"budgets": budgets})
    permit = authority.permit.model_copy(
        update={"spec": spec, "spec_sha256": preparation_spec_fingerprint(spec)}
    )
    binding = authority.binding.model_copy(
        update={"spec": spec, "permit_sha256": preparation_permit_digest(permit)}
    )
    authority = PythonRuntimeAuthorityProjection(permit=permit, binding=binding)
    _seed(database, authority)
    resources = PythonResourceRepository(
        database, node_id="node-test", boot_generation=DomainRef("boot-a"), clock=lambda: NOW
    )
    reservation = resources.reserve(authority, principal_id="core-test")
    inspect = resources.claim(
        reservation.resource_ref,
        operation_id=DomainRef("inspect-test"),
        operation=PythonProviderOperation.INSPECT_INTERPRETER,
        owner_token=DomainRef("owner"),
        lease_seconds=300,
        principal_id="core-test",
    )
    asyncio.run(
        inspect_owned_interpreter(
            configured,
            FakeIdentityBackend(),
            runtime_binding_fixture().backend,
            PythonProvenanceRepository(resources),
            inspect,
            clock=lambda: NOW,
        )
    )
    upgrade_database(database)
    storage = EnvironmentStorage(tmp_path / "environments")
    storage.initialize()
    repository = PythonEnvironmentRepository(resources, storage)
    backend = FakeEnvironmentBackend((configured.distribution_root / "bin/python3.12").read_bytes())
    provider = PythonEnvironmentProvider(
        distribution=configured,
        backend=backend,
        backend_identity=runtime_binding_fixture().backend,
        repository=repository,
        clock=lambda: NOW,
    )
    claim = resources.claim(
        reservation.resource_ref,
        operation_id=DomainRef("environment-test"),
        operation=PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT,
        owner_token=DomainRef("owner-e"),
        lease_seconds=360,
        principal_id="core-test",
    )
    yield Case(database, resources, repository, provider, backend, claim)
    database.close()


def test_success_bound_empty_inventory_and_not_ready(case: Case) -> None:
    evidence = case.create()
    assert case.backend.calls == ["controls", "create", "verify"]
    assert evidence == EmptyEnvironmentEvidence.model_validate_json(evidence.model_dump_json())
    assert (
        evidence.binding.interpreter.distribution
        == inventory(case.provider.distribution).identity()
    )
    assert evidence.binding.interpreter.distribution is not None
    assert evidence.environment.external_installed_dependencies == ()
    assert evidence.environment.pip_bootstrapped is False
    assert evidence.environment.total_bytes > 0
    assert case.repository.inspect_retained(case.claim.resource_ref) == evidence
    state = case.resources.load(case.claim.resource_ref)
    assert (state.state, state.phase, state.validity) == (
        PythonResourceState.CREATING,
        PythonProviderPhase.VERIFYING,
        PythonRuntimeValidity.UNCHECKED,
    )
    assert case.resources.operations(case.claim.resource_ref)[-1].state is OperationState.COMPLETED
    assert case.path.joinpath("venv/lib/python3.12/site-packages").is_dir()
    assert list(case.path.joinpath("venv/lib/python3.12/site-packages").iterdir()) == []
    with pytest.raises(IntegrityError), case.database.transaction() as session:
        row = session.get(RuntimeResourceRow, str(case.claim.resource_ref))
        assert row is not None
        row.state = "READY"


def test_same_operation_replay_does_not_build_or_spend_twice(case: Case) -> None:
    original = case.create()
    ledger = case.resources.budget(case.claim.resource_ref)
    assert case.create() == original
    assert case.backend.calls == ["controls", "create", "verify"]
    assert case.resources.budget(case.claim.resource_ref) == ledger


def test_verifying_without_evidence_is_forbidden(case: Case) -> None:
    with (
        pytest.raises(IntegrityError, match="requires retained"),
        case.database.transaction() as session,
    ):
        row = session.get(PythonResourceRow, str(case.claim.resource_ref))
        assert row is not None
        row.phase = "VERIFYING"
    assert not case.path.exists()


def test_wrong_owner_cannot_poison_completed_resource(case: Case) -> None:
    evidence = case.create()
    wrong = case.claim.model_copy(update={"owner_token": DomainRef("wrong-owner")})
    with pytest.raises(ResourceOwnershipError, match="ownership/generation"):
        asyncio.run(case.provider.create_empty_environment(wrong))
    assert case.repository.inspect_retained(case.claim.resource_ref) == evidence
    assert case.resources.load(case.claim.resource_ref).phase is PythonProviderPhase.VERIFYING


def test_evidence_and_workspace_immutable(case: Case) -> None:
    evidence = case.create()
    with pytest.raises(IntegrityError), case.database.transaction() as session:
        row = session.get(PythonEnvironmentRow, str(case.claim.resource_ref))
        assert row is not None
        row.evidence_sha256 = "0" * 64
    with case.database.transaction() as session:
        assert session.execute(text("SELECT owner_ref,purpose FROM workspaces")).one() == (
            str(case.claim.resource_ref),
            "python-empty-environment",
        )
    assert evidence.generation == case.claim.generation
    assert evidence.construction.group_empty and evidence.verification.group_empty


@pytest.mark.parametrize(
    "mutation",
    ["missing", "binary", "config", "pip", "ensurepip", "pth", "customize", "symlink", "hardlink"],
)
def test_retained_drift_missing_packages_and_startup_never_repair(
    case: Case, mutation: str
) -> None:
    case.create()
    root = case.path / "venv"
    if mutation == "missing":
        (root / "bin/python3.12").unlink()
    elif mutation in {"binary", "config"}:
        (root / ("bin/python3.12" if mutation == "binary" else "pyvenv.cfg")).write_bytes(
            b"altered"
        )
    elif mutation == "symlink":
        (root / "bin/python").unlink()
        (root / "bin/python").symlink_to("/usr/bin/python3")
    elif mutation == "hardlink":
        (root / "bin/python").unlink()
        (root / "bin/python").hardlink_to(root / "bin/python3.12")
    else:
        (
            root
            / "lib/python3.12/site-packages"
            / {"pth": "host.pth", "customize": "sitecustomize.py"}.get(mutation, mutation)
        ).write_bytes(b"do not import")
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert case.resources.load(case.claim.resource_ref).state is PythonResourceState.LOST
    assert case.backend.calls == ["controls", "create", "verify"]


@pytest.mark.parametrize("failure", ["create", "verify", "cancel"])
def test_failed_or_cancelled_construction_retains_full_unsettled_reservation(
    case: Case, failure: str
) -> None:
    case.backend.failure = failure
    with pytest.raises((RuntimeConfinementUnavailable, asyncio.CancelledError)):
        case.create()
    assert case.repository.history(case.claim.resource_ref) is None
    assert case.resources.load(case.claim.resource_ref).phase is PythonProviderPhase.QUARANTINED
    assert all(balance.held == 0 for balance in case.resources.budget(case.claim.resource_ref))
    with pytest.raises(ResourceOwnershipError):
        case.resources.claim(
            case.claim.resource_ref,
            operation_id=DomainRef("new-owner"),
            operation=PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT,
            owner_token=DomainRef("new-owner"),
            principal_id="core-test",
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"group_empty": False},
        {"passed": False},
        {"pids_events": 1},
        {"oom_events": 1},
        {"memory_peak": 200 * 1024**2},
        {"stop_reason": "OUTPUT", "passed": False},
        {"helper_sha256": "f" * 64},
    ],
)
def test_incomplete_confinement_proof_cannot_publish_success(
    case: Case, updates: dict[str, object]
) -> None:
    case.backend.proof_updates = updates
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert case.repository.history(case.claim.resource_ref) is None
    assert case.resources.load(case.claim.resource_ref).state is PythonResourceState.LOST


@pytest.mark.parametrize(
    "updates",
    [
        {"paths": ["/usr/lib/python3.12"]},
        {"user_site": True},
        {"version": "3.13.7"},
        {"base_prefix": "/host"},
        {"isolated": 0},
        {"no_bytecode": False},
    ],
)
def test_unexpected_environment_identity_denies(case: Case, updates: dict[str, object]) -> None:
    case.backend.identity_updates = updates
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert case.repository.history(case.claim.resource_ref) is None


def test_existing_partial_directory_denied_without_overwrite(case: Case) -> None:
    case.path.mkdir()
    (case.path / "sentinel").write_bytes(b"partial evidence")
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert (case.path / "sentinel").read_bytes() == b"partial evidence"
    assert case.backend.calls == []


def test_no_provenance_and_changed_provenance_denied_before_child(case: Case) -> None:
    (case.provider.distribution.distribution_root / "lib/python3.12/json.py").write_bytes(
        b"changed"
    )
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert case.backend.calls == []


def test_restart_success_keeps_history_but_never_current_valid(case: Case) -> None:
    evidence = case.create()
    case.database.close()
    reopened = RuntimeDatabase(case.database.path)
    try:
        resources = PythonResourceRepository(
            reopened, node_id="node-test", boot_generation=DomainRef("boot-b"), clock=lambda: NOW
        )
        repository = PythonEnvironmentRepository(resources, case.repository.storage)
        assert resources.reconcile() == 0
        assert repository.reconcile_retained() == 0
        assert repository.inspect_retained(case.claim.resource_ref) == evidence
        assert resources.load(case.claim.resource_ref).validity is PythonRuntimeValidity.UNCHECKED
        assert resources.load(case.claim.resource_ref).state is PythonResourceState.CREATING
    finally:
        reopened.close()


def test_restart_active_owner_quarantines_without_refund(case: Case) -> None:
    case.resources.reserve_budget(
        case.claim, (BudgetAmount(category=BudgetCategory.WRITE_BYTES, amount=1234),)
    )
    case.resources.mark_building(case.claim)
    case.path.mkdir()
    (case.path / "partial").write_bytes(b"incomplete")
    recovered = PythonResourceRepository(
        case.database, node_id="node-test", boot_generation=DomainRef("boot-b"), clock=lambda: NOW
    )
    assert recovered.reconcile() == 1
    assert recovered.load(case.claim.resource_ref).state is PythonResourceState.LOST
    assert (
        next(
            b
            for b in recovered.budget(case.claim.resource_ref)
            if b.category is BudgetCategory.WRITE_BYTES
        ).held
        == 0
    )
    assert case.repository.history(case.claim.resource_ref) is None


def test_stale_ownership_denied_before_child(case: Case) -> None:
    case.resources._clock = lambda: NOW + timedelta(seconds=361)
    with pytest.raises(ResourceOwnershipError):
        case.create()
    assert case.backend.calls == []


def test_budget_exhaustion_denied_before_child(case: Case) -> None:
    # Existing D spending plus E reservation must both fit; cannot reset baseline.
    with case.database.transaction() as session:
        session.execute(
            text(
                "UPDATE python_resource_budget_entries SET spent=reserved WHERE operation_id='inspect-test'"
            )
        )
    case.resources.reserve_budget(
        case.claim, (BudgetAmount(category=BudgetCategory.WRITE_BYTES, amount=200 * 1024**2),)
    )
    with pytest.raises(ResourceOwnershipError):
        case.create()
    assert case.backend.calls == []


def test_upgrade_preserves_populated_d_history(case: Case, tmp_path: Path) -> None:
    assert current_revision(case.database) == "0011_empty_python_environment"
    assert len(PythonProvenanceRepository(case.resources).history(case.claim.resource_ref)) == 1
    with case.database.transaction() as session:
        assert session.execute(text("PRAGMA foreign_key_check")).first() is None
    # A second DB begins at D, with actual FK-linked resource/provenance history.
    database = RuntimeDatabase(tmp_path / "upgrade.sqlite3")
    upgrade_database(database, "0010_python_provenance")
    with database.transaction() as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
    upgrade_database(database)
    assert current_revision(database) == "0011_empty_python_environment"
    with database.transaction() as session:
        assert session.execute(text("PRAGMA foreign_key_check")).first() is None
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
    database.close()


def test_environment_identity_schema_rejects_arbitrary_inputs() -> None:
    with pytest.raises(ValueError):
        EnvironmentIdentity.model_validate_json(
            '{"argv":["evil"],"environment":{"PYTHONPATH":"evil"}}'
        )


@pytest.mark.parametrize(
    "case",
    [
        "sitecustomize.py",
        "usercustomize.py",
        "sitecustomize/__init__.py",
        "usercustomize.pyc",
        "startup.pth",
        "lib-dynload/sitecustomize.py",
    ],
    indirect=True,
)
def test_certified_base_startup_hooks_are_rejected_before_site_enabled_verifier(case: Case) -> None:
    assert len(PythonProvenanceRepository(case.resources).history(case.claim.resource_ref)) == 1
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert case.backend.calls == []
    assert case.repository.history(case.claim.resource_ref) is None
    assert case.resources.load(case.claim.resource_ref).phase is PythonProviderPhase.QUARANTINED


@pytest.mark.parametrize(
    "defect",
    ["truncated", "trailing", "corrupt", "overflow-header", "unsafe-path", "too-many-inodes"],
)
def test_malformed_or_oversized_export_never_reaches_success(case: Case, defect: str) -> None:
    if defect == "truncated":
        case.backend.export = case.backend.export[:-1]
    elif defect == "trailing":
        case.backend.export += b"unexpected"
    elif defect == "corrupt":
        case.backend.export = case.backend.export[:-1] + b"X"
    elif defect == "overflow-header":
        case.backend.export = struct.pack("!I", 65533) + b"{}"
    else:
        manifest = case.backend.manifest.model_dump(mode="json")
        entries = manifest["entries"]
        assert isinstance(entries, list)
        if defect == "unsafe-path":
            entries[0]["path"] = "../../escape"
        else:
            entries.extend([entries[0]] * 256)
        encoded = json.dumps(manifest).encode()
        case.backend.export = struct.pack("!I", len(encoded)) + encoded
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert "verify" not in case.backend.calls
    assert case.repository.history(case.claim.resource_ref) is None
    assert case.resources.load(case.claim.resource_ref).phase is PythonProviderPhase.QUARANTINED


def test_crash_after_publish_cannot_reconstruct_evidence_from_bytes(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(claim: ResourceOperation, evidence: EmptyEnvironmentEvidence) -> None:
        raise RuntimeError("interrupted DB completion")

    monkeypatch.setattr(case.repository, "complete", crash)
    with pytest.raises(EnvironmentFailure):
        case.create()
    assert (case.path / "venv/bin/python3.12").is_file()
    assert case.repository.history(case.claim.resource_ref) is None
    assert case.resources.load(case.claim.resource_ref).state is PythonResourceState.LOST
    with pytest.raises(EnvironmentFailure):
        case.repository.inspect_retained(case.claim.resource_ref)


def test_missing_environment_on_restart_retains_historical_evidence(case: Case) -> None:
    evidence = case.create()
    (case.path / "venv/pyvenv.cfg").unlink()
    assert case.repository.reconcile_retained() == 1
    assert case.repository.history(case.claim.resource_ref) == evidence
    assert case.resources.load(case.claim.resource_ref).state is PythonResourceState.LOST


def test_duplicate_active_request_does_not_poison_owner(case: Case) -> None:
    async def exercise() -> None:
        entered, released = asyncio.Event(), asyncio.Event()
        original = case.backend.check

        async def blocked(features: tuple[object, ...]) -> object:
            entered.set()
            await released.wait()
            return await original(features)  # type: ignore[arg-type]

        # Narrow test-only async gate; no production injection hook.
        case.backend.check = blocked  # type: ignore[assignment]
        task = asyncio.create_task(case.provider.create_empty_environment(case.claim))
        await entered.wait()
        try:
            with pytest.raises(ResourceOwnershipError, match="already owned"):
                await case.provider.create_empty_environment(case.claim)
            assert (
                case.resources.load(case.claim.resource_ref).phase is PythonProviderPhase.BUILDING
            )
        finally:
            released.set()
        evidence = await task
        assert evidence.phase == "VERIFYING"

    asyncio.run(exercise())
    assert case.backend.calls == ["controls", "create", "verify"]


def test_source_and_secret_canaries_are_never_provider_inputs(
    case: Case, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sentinel = tmp_path / "acquired-source.py"
    original = b"raise RuntimeError('source must not execute')\n"
    sentinel.write_bytes(original)
    secret = "HARMLESS_E5E_CANARY_NOT_AN_EXECUTION_INPUT"
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("BOBERAGENT_MCP_TOKEN", secret)
    evidence = case.create()
    assert sentinel.read_bytes() == original
    assert secret not in evidence.model_dump_json()
    assert evidence.provenance.non_actions.source_imported is False
    assert evidence.provenance.non_actions.target_secret_grants == ()
