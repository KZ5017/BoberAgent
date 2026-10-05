"""Portable E5-D synthetic bytes/identity: never a claim of real Linux enforcement."""

import asyncio
import hashlib
import json
import os
import shutil
import stat
import struct
from collections.abc import Iterator
from pathlib import Path

import pytest
from boberagent_contracts import (
    ConfinementFeature,
    DomainRef,
    PythonProviderOperation,
    PythonResourceState,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeReason,
    PythonRuntimeValidity,
    preparation_permit_digest,
    preparation_spec_fingerprint,
)
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import current_revision, upgrade_database
from boberagent_execution_node.persistence.orm import PythonRuntimeEvidenceRow
from boberagent_execution_node.preparation import python_distribution as distribution
from boberagent_execution_node.preparation.python_distribution import (
    MANIFEST_ADAPTER,
    ProvenanceFailure,
    PythonDistributionConfiguration,
    inventory,
    revalidate,
)
from boberagent_execution_node.preparation.python_provenance import (
    PythonProvenanceRepository,
    inspect_owned_interpreter,
    validate_identity,
)
from boberagent_execution_node.preparation.resources import PythonResourceRepository
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ClosedProbe,
    ConfinementCheck,
    ProbeEvidence,
    ProbeLimits,
    StopReason,
    TrustedPythonOperation,
)
from plan_test_fixtures import NOW
from pydantic import ValidationError
from python_runtime_test_fixtures import runtime_authority_fixture, runtime_binding_fixture
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_python_resource_ownership import _seed


def elf(*, interpreter: bool = False) -> bytes:
    """Structurally valid minimal x86_64 ELF, intentionally not executable Python."""
    data = bytearray(512)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", data, 16, 3, 62)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 2 if interpreter else 1)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, len(data), len(data), 4096)
    if interpreter:
        loader = b"/lib64/ld-linux-x86-64.so.2\0"
        data[256 : 256 + len(loader)] = loader
        struct.pack_into("<IIQQQQQQ", data, 120, 3, 4, 256, 256, 0, len(loader), len(loader), 1)
    return bytes(data)


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PythonDistributionConfiguration:
    # Only portable fixtures bypass /tmp's writable substitution parent. Production
    # denies it; all distribution and test parents still undergo real mode checks.
    original = distribution._parents

    def fixture_parents(path: Path) -> list[tuple[str, int, int, int, int, int]]:
        result = []
        for parent in (path, *path.parents):
            if not parent.is_relative_to(tmp_path):
                break
            info = parent.lstat()
            distribution._trust(info)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("fixture parent")
            result.append(
                (
                    str(parent),
                    info.st_dev,
                    info.st_ino,
                    info.st_uid,
                    info.st_gid,
                    stat.S_IMODE(info.st_mode),
                )
            )
        return result

    assert original is not fixture_parents
    monkeypatch.setattr(distribution, "_parents", fixture_parents)
    root, libraries = tmp_path / "python", tmp_path / "libraries"
    for path in (
        root / "bin",
        root / "lib/python3.12/lib-dynload",
        root / "lib/python3.12/venv",
        libraries,
    ):
        path.mkdir(parents=True, mode=0o755)
    (root / "bin/python3.12").write_bytes(elf(interpreter=True))
    (root / "bin/python3.12").chmod(0o755)
    (root / "lib/python3.12/venv/__init__.py").write_bytes(b"# trusted stdlib fixture\n")
    (root / "lib/python3.12/json.py").write_bytes(b"# synthetic stdlib\n")
    (libraries / "ld-linux-x86-64.so.2").write_bytes(elf())
    for path in (
        root / "lib/python3.12/venv/__init__.py",
        root / "lib/python3.12/json.py",
        libraries / "ld-linux-x86-64.so.2",
    ):
        path.chmod(0o644)
    config = PythonDistributionConfiguration(
        distribution_root=root,
        system_library_root=libraries,
        expected_manifest_sha256="0" * 64,
        expected_interpreter_sha256="0" * 64,
    )
    manifest = inventory(config, verify_pins=False)
    return config.model_copy(
        update={
            "expected_manifest_sha256": manifest.digest,
            "expected_interpreter_sha256": manifest.interpreter_sha256,
        }
    )


def repin(config: PythonDistributionConfiguration) -> PythonDistributionConfiguration:
    manifest = inventory(config, verify_pins=False)
    return config.model_copy(
        update={
            "expected_manifest_sha256": manifest.digest,
            "expected_interpreter_sha256": manifest.interpreter_sha256,
        }
    )


def identity_probe(**changes: object) -> ProbeEvidence:
    identity: dict[str, object] = dict(
        implementation="cpython",
        version="3.12.14",
        platform="linux",
        architecture="x86_64",
        cache_tag="cpython-312",
        soabi="cpython-312-x86_64-linux-gnu",
        prefix="/runtime",
        base_prefix="/runtime",
        executable="/runtime/bin/python3.12",
        paths=[
            "/runtime/lib/python312.zip",
            "/runtime/lib/python3.12",
            "/runtime/lib/python3.12/lib-dynload",
        ],
        isolated=1,
        no_site=1,
        no_bytecode=True,
    )
    identity.update(changes)
    return ProbeEvidence(
        operation_id=DomainRef("inspect-test"),
        boot_generation=DomainRef("boot-a"),
        probe=TrustedPythonOperation.IDENTITY,
        helper_sha256="a" * 64,
        bubblewrap_sha256="9" * 64,
        kernel="synthetic-not-host-proof",
        limits=ProbeLimits(),
        attached_before_exec=True,
        exit_code=0,
        stop_reason=StopReason.EXITED,
        pids_events=0,
        oom_events=0,
        memory_peak=1024**2,
        process_peak_upper_bound=8,
        duration_milliseconds=10,
        stdout_hex=json.dumps(identity).encode().hex(),
        stderr_hex="",
        group_empty=True,
        passed=True,
    )


class FakeIdentityBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.identity = identity_probe()

    async def check(self, requirements: tuple[ConfinementFeature, ...]) -> ConfinementCheck:
        self.calls.append("controls")
        return ConfinementCheck(
            features=requirements,
            probes=tuple(
                self.identity.model_copy(update={"probe": p, "passed": True}) for p in ClosedProbe
            ),
        )

    async def run_identity(
        self, configuration: PythonDistributionConfiguration, operation_id: DomainRef
    ) -> ProbeEvidence:
        inventory(configuration)
        self.calls.append("identity")
        return self.identity.model_copy(update={"operation_id": operation_id})


def test_exact_family_and_full_canonical_closure(
    configured: PythonDistributionConfiguration,
) -> None:
    manifest = inventory(configured)
    identity = validate_identity(manifest, identity_probe())
    assert identity.summary.python_version == "3.12.14"
    assert identity.distribution == manifest.identity()
    assert identity.closure_sha256 != identity.summary.executable_sha256
    assert identity.distribution is not None
    assert identity.distribution.interpreter_relative_path == "bin/python3.12"
    assert "venv/__init__.py" in " ".join(e.path for e in manifest.entries)
    assert MANIFEST_ADAPTER.validate_json(manifest.model_dump_json()) == manifest
    # Ordered canonical entries don't depend on directory iteration order or mtimes.
    os.utime(configured.distribution_root / "lib/python3.12/json.py", (1, 1))
    assert inventory(configured) == manifest


@pytest.mark.parametrize(
    "changes",
    [
        dict(version="3.13.1"),
        dict(version="3.11.9"),
        dict(version="3.12.14-dev"),
        dict(implementation="pypy"),
        dict(architecture="aarch64"),
        dict(platform="win32"),
        dict(isolated=0),
        dict(no_site=0),
        dict(no_bytecode=False),
        dict(prefix="/other"),
        dict(executable="/other/python"),
        dict(paths=[".", "/user/site"]),
        dict(unexpected="data"),
    ],
)
def test_identity_rejects_incompatible_or_unisolated(
    configured: PythonDistributionConfiguration, changes: dict[str, object]
) -> None:
    with pytest.raises(ProvenanceFailure) as error:
        validate_identity(inventory(configured), identity_probe(**changes))
    assert error.value.failure.runtime_reason is PythonRuntimeReason.PYTHON_RUNTIME_MISMATCH
    assert "data" not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        dict(
            passed=False,
            exit_code=1,
            stdout_hex="",
            stop_reason=StopReason.OUTPUT,
            stderr_hex=b"usage: /usr/bin/bwrap [OPTIONS...] [--] COMMAND [ARGS...]".hex(),
        ),
        dict(passed=False, exit_code=90, stop_reason=StopReason.START_FAILED),
        dict(passed=False, exit_code=None, stop_reason=StopReason.TIMEOUT),
        dict(attached_before_exec=False),
        dict(group_empty=False),
        dict(pids_events=1),
        dict(oom_events=1),
        dict(stderr_hex=b"bounded operation error".hex()),
    ],
)
def test_failed_fixed_operation_is_not_an_interpreter_identity_mismatch(
    configured: PythonDistributionConfiguration, changes: dict[str, object]
) -> None:
    probe = ProbeEvidence.model_validate({**identity_probe().model_dump(), **changes})
    with pytest.raises(ProvenanceFailure) as error:
        validate_identity(inventory(configured), probe)
    assert error.value.failure.runtime_reason is PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE
    assert error.value.failure.reason_code.value == "RUNTIME_UNAVAILABLE"
    assert error.value.stage == "identity_result"
    assert "/usr/bin/bwrap" not in str(error.value) and "usage" not in str(error.value)


def test_successful_operation_with_malformed_identity_still_rejects_as_mismatch(
    configured: PythonDistributionConfiguration,
) -> None:
    probe = identity_probe().model_copy(update={"stdout_hex": b"not identity JSON".hex()})
    with pytest.raises(ProvenanceFailure) as error:
        validate_identity(inventory(configured), probe)
    assert error.value.failure.runtime_reason is PythonRuntimeReason.PYTHON_RUNTIME_MISMATCH


@pytest.mark.parametrize("relative", ["bin/python3.12", "lib/python3.12/json.py"])
def test_changed_runtime_bytes_invalidates(
    configured: PythonDistributionConfiguration, relative: str
) -> None:
    identity = inventory(configured).identity()
    path = configured.distribution_root / relative
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ProvenanceFailure):
        inventory(configured)
    with pytest.raises(ProvenanceFailure) as error:
        revalidate(configured, identity)
    assert error.value.failure.runtime_reason is PythonRuntimeReason.RUNTIME_REVALIDATION_FAILED


@pytest.mark.parametrize("mode", [0o664, 0o666, 0o6755])
def test_writable_or_privileged_file_rejected(
    configured: PythonDistributionConfiguration, mode: int
) -> None:
    (configured.distribution_root / "bin/python3.12").chmod(mode)
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_missing_and_no_path_fallback(
    configured: PythonDistributionConfiguration, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(configured.distribution_root / "bin"))
    (configured.distribution_root / "bin/python3.12").unlink()
    with pytest.raises(ProvenanceFailure) as error:
        inventory(configured)
    assert error.value.failure.runtime_reason is PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE
    with pytest.raises(ValidationError):
        PythonDistributionConfiguration(
            distribution_root=Path("relative"),
            system_library_root=Path("/usr/lib"),
            expected_manifest_sha256="0" * 64,
            expected_interpreter_sha256="0" * 64,
        )


def test_owner_and_substitution_parent(
    configured: PythonDistributionConfiguration, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured.distribution_root.parent.chmod(0o777)
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)
    configured.distribution_root.parent.chmod(0o700)


def test_wrong_owner(
    configured: PythonDistributionConfiguration, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = os.getuid()
    if uid == 0:
        pytest.skip("root is an approved ownership class")
    monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_one_hop_links_and_escape(configured: PythonDistributionConfiguration) -> None:
    root = configured.distribution_root
    (root / "bin/python3").symlink_to("python3.12")
    safe = repin(configured)
    assert any(
        e.path == "bin/python3" and e.target == "python3.12" for e in inventory(safe).entries
    )
    (root / "bin/chain").symlink_to("python3")
    with pytest.raises(ProvenanceFailure):
        inventory(safe, verify_pins=False)
    (root / "bin/chain").unlink()
    (root / "bin/escape").symlink_to("../../outside")
    with pytest.raises(ProvenanceFailure):
        inventory(safe, verify_pins=False)


@pytest.mark.parametrize(
    "data", [b"{", b"[]", b"x" * 150000], ids=["malformed", "array", "oversized"]
)
def test_malformed_metadata(configured: PythonDistributionConfiguration, data: bytes) -> None:
    (configured.distribution_root / "PYTHON.json").write_bytes(data)
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_metadata_support_caches_and_root_binding(
    configured: PythonDistributionConfiguration, tmp_path: Path
) -> None:
    root = configured.distribution_root
    (root / "PYTHON.json").write_text('{"python_version":"3.12.14"}')
    good = repin(configured)
    manifest = inventory(good)
    assert (
        manifest.metadata_sha256 == hashlib.sha256((root / "PYTHON.json").read_bytes()).hexdigest()
    )
    # Caches Python can read ARE runtime identity; unrelated unmounted noise is not.
    (root / "operator-notes").write_text("unmounted noise")
    assert inventory(good) == manifest
    (root / "lib/python3.12/cache.pyc").write_bytes(b"cache")
    with pytest.raises(ProvenanceFailure):
        inventory(good)
    (root / "lib/python3.12/cache.pyc").unlink()
    (good.system_library_root / "ld-linux-x86-64.so.2").write_bytes(elf() + b"mutated")
    with pytest.raises(ProvenanceFailure):
        inventory(good)
    copy = tmp_path / "replacement"
    shutil.copytree(root, copy)
    moved = good.model_copy(update={"distribution_root": copy})
    with pytest.raises(ProvenanceFailure):
        revalidate(moved, manifest.identity())


def owned(
    database: RuntimeDatabase, *, temporary_bytes: int = 20 * 1024**2, file_count: int = 4000
) -> tuple[PythonResourceRepository, PythonProvenanceRepository]:
    authority = runtime_authority_fixture()
    # Real ownership admission with roomy synthetic budgets for fourteen fixed ops.
    budgets = authority.permit.spec.budgets.model_copy(
        update={
            "max_processes": 11,
            "max_total_runtime_seconds": 600,
            "max_preparation_write_bytes": 64 * 1024**2,
            "max_temporary_bytes": temporary_bytes,
            "max_file_count": file_count,
            "max_captured_output_bytes": 100000,
        }
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
    resources.reserve(authority, principal_id="core-test")
    return resources, PythonProvenanceRepository(resources)


@pytest.mark.parametrize("limits", [dict(temporary_bytes=2 * 1024**2), dict(file_count=2000)])
def test_projection_control_overhead_must_fit_existing_authority(
    configured: PythonDistributionConfiguration, tmp_path: Path, limits: dict[str, int]
) -> None:
    from boberagent_contracts import PreparationReasonCode, ResourceRef
    from boberagent_execution_node.preparation.resources import ResourceOwnershipError

    database = RuntimeDatabase(tmp_path / "bounded-control.sqlite3")
    upgrade_database(database)
    resources, repository = owned(database, **limits)
    with database.transaction() as session:
        resource = ResourceRef(
            session.scalar(text("SELECT resource_id FROM python_resource_details"))
        )
    claim = resources.claim(
        resource,
        operation_id=DomainRef("inspect-bounded"),
        operation=PythonProviderOperation.INSPECT_INTERPRETER,
        owner_token=DomainRef("owner"),
        lease_seconds=300,
        principal_id="core-test",
    )
    backend = FakeIdentityBackend()
    with pytest.raises(ResourceOwnershipError) as failure:
        asyncio.run(
            inspect_owned_interpreter(
                configured,
                backend,
                runtime_binding_fixture().backend,
                repository,
                claim,
                clock=lambda: NOW,
            )
        )
    assert failure.value.code is PreparationReasonCode.WORKSPACE_LIMIT_EXCEEDED
    assert backend.calls == [] and repository.history(resource) == ()
    assert resources.load(resource).state is PythonResourceState.LOST
    from boberagent_contracts import PythonProviderPhase

    assert resources.load(resource).phase is PythonProviderPhase.QUARANTINED
    database.close()


def test_owned_inspection_restart_history_and_no_ready(
    configured: PythonDistributionConfiguration, tmp_path: Path
) -> None:
    database = RuntimeDatabase(tmp_path / "runtime.sqlite3")
    upgrade_database(database)
    assert current_revision(database) == "0011_empty_python_environment"
    resources, repository = owned(database)
    with database.transaction() as session:
        ref = session.scalar(text("SELECT resource_id FROM python_resource_details"))
    from boberagent_contracts import ResourceRef

    resource = ResourceRef(ref)
    claim = resources.claim(
        resource,
        operation_id=DomainRef("inspect-test"),
        operation=PythonProviderOperation.INSPECT_INTERPRETER,
        owner_token=DomainRef("owner"),
        lease_seconds=300,
        principal_id="core-test",
    )
    backend = FakeIdentityBackend()
    evidence = asyncio.run(
        inspect_owned_interpreter(
            configured,
            backend,
            runtime_binding_fixture().backend,
            repository,
            claim,
            clock=lambda: NOW,
        )
    )
    assert backend.calls == ["controls", "identity"]
    assert evidence.verification == "PROVENANCE_VERIFIED" and evidence.environment is None
    assert resources.load(resource).state is PythonResourceState.CREATING
    assert resources.load(resource).validity is PythonRuntimeValidity.UNCHECKED
    repository.complete(claim, evidence, inventory(configured))  # immutable ack/replay
    with pytest.raises(IntegrityError), database.transaction() as session:
        row = session.get(PythonRuntimeEvidenceRow, str(claim.operation_id))
        assert row is not None
        row.evidence_sha256 = "f" * 64
    database.close()
    reopened = RuntimeDatabase(database.path)
    refreshed = PythonResourceRepository(
        reopened, node_id="node-test", boot_generation=DomainRef("boot-b"), clock=lambda: NOW
    )
    assert refreshed.reconcile() == 0
    history = PythonProvenanceRepository(refreshed).history(resource)
    assert history == (evidence,)
    assert refreshed.load(resource).state is PythonResourceState.CREATING
    assert evidence.binding.interpreter.distribution is not None
    assert revalidate(configured, evidence.binding.interpreter.distribution) == inventory(
        configured
    )
    reopened.close()


def test_static_failure_never_executes_and_is_inspectable(
    configured: PythonDistributionConfiguration, tmp_path: Path
) -> None:
    database = RuntimeDatabase(tmp_path / "failed.sqlite3")
    upgrade_database(database)
    resources, repository = owned(database)
    with database.transaction() as session:
        ref = session.scalar(text("SELECT resource_id FROM python_resource_details"))
    from boberagent_contracts import ResourceRef

    resource = ResourceRef(ref)
    claim = resources.claim(
        resource,
        operation_id=DomainRef("inspect-test"),
        operation=PythonProviderOperation.INSPECT_INTERPRETER,
        owner_token=DomainRef("owner"),
        lease_seconds=300,
        principal_id="core-test",
    )
    (configured.distribution_root / "lib/python3.12/json.py").write_bytes(b"bad")
    backend = FakeIdentityBackend()
    with pytest.raises(ProvenanceFailure):
        asyncio.run(
            inspect_owned_interpreter(
                configured,
                backend,
                runtime_binding_fixture().backend,
                repository,
                claim,
                clock=lambda: NOW,
            )
        )
    assert backend.calls == [] and repository.history(resource) == ()
    assert resources.operations(resource)[0].failure is not None
    database.close()
    reopened = RuntimeDatabase(database.path)
    refreshed = PythonResourceRepository(
        reopened, node_id="node-test", boot_generation=DomainRef("boot-b"), clock=lambda: NOW
    )
    assert refreshed.reconcile() == 0
    assert refreshed.load(resource).state is PythonResourceState.LOST
    assert PythonProvenanceRepository(refreshed).history(resource) == ()
    reopened.close()


def test_interrupted_inspect_claim_reopens_quarantined_without_evidence(tmp_path: Path) -> None:
    from boberagent_contracts import ResourceRef

    database = RuntimeDatabase(tmp_path / "interrupted.sqlite3")
    upgrade_database(database)
    resources, _repository = owned(database)
    with database.transaction() as session:
        ref = ResourceRef(session.scalar(text("SELECT resource_id FROM python_resource_details")))
    resources.claim(
        ref,
        operation_id=DomainRef("interrupted-inspect"),
        operation=PythonProviderOperation.INSPECT_INTERPRETER,
        owner_token=DomainRef("owner"),
        lease_seconds=300,
        principal_id="core-test",
    )
    database.close()
    reopened = RuntimeDatabase(database.path)
    recovered = PythonResourceRepository(
        reopened, node_id="node-test", boot_generation=DomainRef("boot-b"), clock=lambda: NOW
    )
    assert recovered.reconcile() == 1
    assert recovered.load(ref).state is PythonResourceState.LOST
    assert recovered.operations(ref)[0].failure is not None
    assert PythonProvenanceRepository(recovered).history(ref) == ()
    reopened.close()


def test_migration_from_c_preserves_old_journal_and_ready_guards(tmp_path: Path) -> None:
    database = RuntimeDatabase(tmp_path / "upgrade.sqlite3")
    upgrade_database(database, "0009_runtime_confinement")
    with database.transaction() as session:
        session.execute(
            text(
                "INSERT INTO runtime_confinement_operations (operation_id,probe,limits_json,boot_generation,host_boot,parent_sha256,state,started_at) VALUES ('old-probe','isolation','{}','old-boot','host','pin','INTERRUPTED','2026-01-01')"
            )
        )
    upgrade_database(database)
    upgrade_database(database)
    with database.transaction() as session:
        assert session.execute(
            text("SELECT operation_id,state,input_sha256 FROM runtime_confinement_operations")
        ).one() == ("old-probe", "INTERRUPTED", None)
        assert session.scalar(text("SELECT count(*) FROM python_runtime_evidence")) == 0
    assert current_revision(database) == "0011_empty_python_environment"
    database.close()


def test_identity_operation_journal_rejects_changed_distribution_input(tmp_path: Path) -> None:
    from boberagent_execution_node.preparation.runtime_confinement_store import ConfinementJournal

    database = RuntimeDatabase(tmp_path / "journal.sqlite3")
    upgrade_database(database)
    journal = ConfinementJournal(database)
    probe = identity_probe()
    journal.begin(
        probe.operation_id,
        probe.probe,
        probe.limits,
        probe.boot_generation,
        "host",
        "parent",
        NOW,
        input_sha256="a" * 64,
    )
    journal.finish(probe, NOW)
    assert (
        journal.begin(
            probe.operation_id,
            probe.probe,
            probe.limits,
            DomainRef("new-boot"),
            "host",
            "parent",
            NOW,
            input_sha256="a" * 64,
        )
        == probe
    )
    with pytest.raises(ValueError, match="conflicting"):
        journal.begin(
            probe.operation_id,
            probe.probe,
            probe.limits,
            probe.boot_generation,
            "host",
            "parent",
            NOW,
            input_sha256="b" * 64,
        )
    database.close()


def test_malformed_or_incomplete_identity_evidence(
    configured: PythonDistributionConfiguration,
) -> None:
    for update in (
        {"stdout_hex": b"{bad".hex()},
        {"attached_before_exec": False},
        {"group_empty": False},
        {"pids_events": 1},
        {"passed": False},
        {"stderr_hex": b"private runtime error".hex()},
    ):
        with pytest.raises(ProvenanceFailure) as error:
            validate_identity(inventory(configured), identity_probe().model_copy(update=update))
        assert "private runtime" not in str(error.value)


def test_production_filesystem_ancestor_policy_denies_tmp_and_links(tmp_path: Path) -> None:
    with pytest.raises(ProvenanceFailure):
        distribution._parents(tmp_path)


def test_wrong_elf_architecture_and_missing_venv(
    configured: PythonDistributionConfiguration,
) -> None:
    path = configured.distribution_root / "bin/python3.12"
    data = bytearray(path.read_bytes())
    struct.pack_into("<H", data, 18, 183)
    path.write_bytes(data)
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)
    path.write_bytes(elf(interpreter=True))
    (configured.distribution_root / "lib/python3.12/venv/__init__.py").unlink()
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def dynamic_elf(needed: str, rpath: str = "$ORIGIN") -> bytes:
    data = bytearray(elf())
    struct.pack_into("<HH", data, 54, 56, 2)
    strings = needed.encode() + b"\0" + rpath.encode() + b"\0"
    data[384 : 384 + len(strings)] = strings
    struct.pack_into("<IIQQQQQQ", data, 120, 2, 4, 256, 256, 0, 80, 80, 8)
    for i, (key, value) in enumerate(
        ((1, 0), (5, 384), (10, len(strings)), (29, len(needed) + 1), (0, 0))
    ):
        struct.pack_into("<qQ", data, 256 + i * 16, key, value)
    return bytes(data)


def test_needed_library_closure_and_escape_rejection(
    configured: PythonDistributionConfiguration,
) -> None:
    root, support = configured.distribution_root, configured.system_library_root
    extension = root / "lib/python3.12/lib-dynload/synthetic.so"
    extension.write_bytes(dynamic_elf("libfixture.so.1"))
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)  # no implicit loader/PATH fallback
    (support / "libfixture.so.1.0").write_bytes(elf())
    (support / "libfixture.so.1").symlink_to("libfixture.so.1.0")
    good = repin(configured)
    manifest = inventory(good)
    assert {e.path for e in manifest.support_entries} == {
        "ld-linux-x86-64.so.2",
        "libfixture.so.1",
        "libfixture.so.1#target",
    }
    extension.write_bytes(dynamic_elf("libfixture.so.1", "$ORIGIN/../../../../outside"))
    with pytest.raises(ProvenanceFailure):
        inventory(good, verify_pins=False)


def test_manifest_order_is_independent_of_directory_iteration(
    configured: PythonDistributionConfiguration, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = inventory(configured)
    original = Path.iterdir

    def reverse(path: Path) -> Iterator[Path]:
        return iter(reversed(list(original(path))))

    monkeypatch.setattr(Path, "iterdir", reverse)
    assert inventory(configured) == manifest
