"""E5-F portable proof wiring. Synthetic backend is not real Kali acceptance."""

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from boberagent_contracts import (
    DomainRef,
    PythonProviderOperation,
    PythonRuntimeEvidence,
    ResourceRef,
)
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.orm import (
    PythonEnvironmentRow,
    PythonRevalidationRow,
    RuntimeResourceRow,
)
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
)
from boberagent_execution_node.preparation.python_environment import (
    EnvironmentFailure,
    PythonEnvironmentProvider,
    PythonEnvironmentRepository,
)
from boberagent_execution_node.preparation.python_revalidation import (
    PythonRevalidationRepository,
    revalidate_environment,
)
from boberagent_execution_node.preparation.resource_models import ResourceOperation
from boberagent_execution_node.preparation.resources import (
    PythonResourceRepository,
    ResourceOwnershipError,
)
from boberagent_execution_node.preparation.runtime_confinement_models import ProbeEvidence
from boberagent_sdk.services.cancellation import CancellationService
from boberagent_sdk.testing.services import FakeArtifactService, FakeCancellationService, FakeClock
from plan_test_fixtures import NOW
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_python_environment import Case
from test_python_environment import case as case
from test_python_provenance import configured as configured


def claim_for(case: Case, name: str = "validate-a") -> ResourceOperation:
    return case.resources.claim(
        case.claim.resource_ref,
        operation_id=DomainRef(name),
        operation=PythonProviderOperation.REVALIDATE,
        owner_token=DomainRef("validation-owner"),
        principal_id="core-test",
        lease_seconds=300,
    )


def validate(case: Case, name: str = "validate-a") -> PythonRuntimeEvidence:
    claim = claim_for(case, name)
    return asyncio.run(
        revalidate_environment(
            PythonRevalidationRepository(case.provider),
            claim,
            verify_source=lambda: None,
            artifacts=FakeArtifactService(
                case.resources.load(claim.resource_ref).request.run_ref, FakeClock(NOW)
            ),
            clock=lambda: NOW,
        )
    )


def test_fresh_promotion_and_replay_preserve_resource_history_and_charges(case: Case) -> None:
    construction = case.create()
    repository = PythonRevalidationRepository(case.provider)
    assert repository.current(case.claim.resource_ref).validity.value == "UNCHECKED"
    before = tuple(case.backend.calls)
    evidence = validate(case)
    assert evidence.verification == "VERIFIED"
    assert evidence.binding == construction.binding
    assert evidence.non_actions.entrypoint_executed is False
    assert evidence.non_actions.target_secret_grants == ()
    assert len(evidence.evidence_artifact_refs) == 1
    current = repository.current(case.claim.resource_ref)
    assert (current.state.value, current.phase.value, current.validity.value) == (
        "READY",
        "PUBLISHED",
        "VALID",
    )
    assert current.boot_generation == DomainRef("boot-a")
    assert tuple(case.backend.calls) == (*before, "controls", "verify")
    balances = case.resources.budget(case.claim.resource_ref)
    assert validate(case) == evidence
    assert case.resources.budget(case.claim.resource_ref) == balances
    assert case.repository.history(case.claim.resource_ref) == construction
    with case.database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(PythonRevalidationRow)) == 1
        assert session.scalar(select(func.count()).select_from(PythonEnvironmentRow)) == 1
        assert session.scalar(select(func.count()).select_from(RuntimeResourceRow)) == 1
        with pytest.raises(IntegrityError):
            session.execute(text("DELETE FROM python_runtime_revalidations"))


@pytest.mark.parametrize("case", [{"max_file_count": 30000}], indirect=True)
def test_restart_clears_current_validity_and_explicit_fresh_validation_required(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    construction = case.create()
    first = validate(case)
    case.database.close()
    case.database = RuntimeDatabase(case.database.path)
    resources = PythonResourceRepository(
        case.database, node_id="node-test", boot_generation=DomainRef("boot-b"), clock=lambda: NOW
    )
    resources.reconcile()
    environment_repository = PythonEnvironmentRepository(resources, case.repository.storage)
    provider = PythonEnvironmentProvider(
        distribution=case.provider.distribution,
        backend=case.backend,
        backend_identity=case.provider.backend_identity,
        repository=environment_repository,
        clock=lambda: NOW,
    )
    case.resources, case.repository, case.provider = resources, environment_repository, provider
    case.backend.identity = case.backend.identity.model_copy(
        update={"boot_generation": DomainRef("boot-b")}
    )
    original_verify = case.backend.run_environment_verify

    async def fresh_verify(
        distribution: PythonDistributionConfiguration,
        operation_id: DomainRef,
        environment_path: Path,
        helper_sha256: str,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence:
        return (
            await original_verify(
                distribution,
                operation_id,
                environment_path,
                helper_sha256,
                cancellation=cancellation,
            )
        ).model_copy(update={"boot_generation": DomainRef("boot-b")})

    monkeypatch.setattr(case.backend, "run_environment_verify", fresh_verify)
    repository = PythonRevalidationRepository(provider)
    assert repository.current(case.claim.resource_ref).validity.value == "UNCHECKED"
    assert repository.history(case.claim.resource_ref) == (first,)
    with pytest.raises(ResourceOwnershipError):
        claim_for(case)  # Same logical owner cannot be resurrected in a different boot.
    second = validate(case, "validate-b")
    assert second.binding == first.binding
    assert repository.current(case.claim.resource_ref).boot_generation == DomainRef("boot-b")
    assert case.repository.history(case.claim.resource_ref) == construction
    case.database.close()


def test_cancelled_revalidation_is_quarantined_without_execution(case: Case) -> None:
    case.create()
    cancellation = FakeCancellationService()
    cancellation.request()
    claim = claim_for(case)
    before = tuple(case.backend.calls)
    with pytest.raises(EnvironmentFailure):
        asyncio.run(
            revalidate_environment(
                PythonRevalidationRepository(case.provider),
                claim,
                verify_source=lambda: None,
                artifacts=FakeArtifactService(
                    case.resources.load(claim.resource_ref).request.run_ref, FakeClock(NOW)
                ),
                cancellation=cancellation,
                clock=lambda: NOW,
            )
        )
    state = case.resources.load(claim.resource_ref)
    assert state.failure and state.failure.reason_code.value == "PREPARATION_CANCELLED"
    assert state.state.value == "LOST"
    assert tuple(case.backend.calls) == before


def test_existing_owned_cleanup_cannot_retain_positive_validity(case: Case) -> None:
    case.create()
    validate(case)
    claim = case.resources.claim(
        case.claim.resource_ref,
        operation_id=DomainRef("cleanup-after-validation"),
        operation=PythonProviderOperation.RELEASE,
        owner_token=DomainRef("cleanup-owner"),
        principal_id="core-test",
    )
    assert case.resources.load(claim.resource_ref).validity.value == "UNCHECKED"
    case.resources.begin_cleanup(claim)
    case.resources.complete_cleanup(claim)
    current = PythonRevalidationRepository(case.provider).current(claim.resource_ref)
    assert (current.state.value, current.phase.value, current.validity.value) == (
        "CLOSED",
        "REMOVED",
        "UNCHECKED",
    )
    # Existing bookkeeping only: no new remote release/storage cleanup implementation.
    assert len(PythonRevalidationRepository(case.provider).history(claim.resource_ref)) == 1


@pytest.mark.parametrize(
    "drift",
    [
        "mutation",
        "missing",
        "package",
        "pth",
        "hook",
        "symlink",
        "ancestor",
        "distribution",
        "helper",
        "backend",
        "identity",
        "failure",
        "source",
    ],
)
def test_drift_never_promotes_or_reconstructs(case: Case, drift: str, tmp_path: Path) -> None:
    case.create()
    original_calls = tuple(case.backend.calls)
    path = case.path / "venv"
    if drift == "mutation":
        (path / "pyvenv.cfg").write_bytes(b"changed")
    elif drift == "missing":
        (path / "bin/python").unlink()
    elif drift in {"package", "pth", "hook"}:
        (
            path
            / "lib/python3.12/site-packages"
            / {"package": "extra.py", "pth": "extra.pth", "hook": "sitecustomize.py"}[drift]
        ).write_bytes(b"raise RuntimeError('must not execute')")
    elif drift == "symlink":
        (path / "bin/python").unlink()
        (path / "bin/python").symlink_to("python3.12")
    elif drift == "ancestor":
        case.repository.storage.root.chmod(0o775)
    elif drift == "distribution":
        (case.provider.distribution.distribution_root / "lib/python3.12/os.py").write_bytes(
            b"changed"
        )
    elif drift == "helper":
        case.provider.helper_sha256 = "0" * 64
    elif drift == "backend":
        case.provider.backend_identity = case.provider.backend_identity.model_copy(
            update={"binary_sha256": "0" * 64}
        )
    elif drift == "identity":
        case.backend.identity_updates["version"] = "3.12.99"
    elif drift == "failure":
        case.backend.failure = "verify"
    claim = claim_for(case)

    def source() -> None:
        if drift == "source":
            raise ValueError("changed source")

    with pytest.raises(EnvironmentFailure):
        asyncio.run(
            revalidate_environment(
                PythonRevalidationRepository(case.provider),
                claim,
                verify_source=source,
                artifacts=FakeArtifactService(
                    case.resources.load(claim.resource_ref).request.run_ref, FakeClock(NOW)
                ),
                clock=lambda: NOW,
            )
        )
    state = case.resources.load(claim.resource_ref)
    assert state.state.value == "LOST" and state.phase.value == "QUARANTINED"
    assert state.validity.value != "VALID"
    assert "create" not in case.backend.calls[len(original_calls) :]
    assert PythonRevalidationRepository(case.provider).history(claim.resource_ref) == ()


def test_wrong_resource_expiry_budget_and_interrupted_owner_are_fail_closed(case: Case) -> None:
    case.create()
    with pytest.raises(KeyError):
        case.resources.claim(
            ResourceRef("wrong"),
            operation_id=DomainRef("wrong-op"),
            operation=PythonProviderOperation.REVALIDATE,
            owner_token=DomainRef("owner"),
            principal_id="core-test",
        )
    case.resources._clock = lambda: NOW + timedelta(hours=1)
    with pytest.raises(ResourceOwnershipError):
        claim_for(case)
    case.resources._clock = lambda: NOW
    claim_for(case)
    with pytest.raises(ResourceOwnershipError):
        claim_for(case, "concurrent")
    case.resources._clock = lambda: NOW + timedelta(minutes=6)
    assert case.resources.reconcile() == 1
    assert case.resources.load(case.claim.resource_ref).state.value == "LOST"


@pytest.mark.parametrize("case", [{"max_file_count": 9000}], indirect=True)
def test_remaining_budget_is_not_reset_and_exhaustion_launches_no_probe(case: Case) -> None:
    case.create()
    before = tuple(case.backend.calls)
    with pytest.raises(EnvironmentFailure):
        validate(case)
    assert tuple(case.backend.calls) == before
    assert case.resources.load(case.claim.resource_ref).state.value == "LOST"


@pytest.mark.parametrize(
    "change",
    [
        {"group_empty": False},
        {"oom_events": 1},
        {"pids_events": 1},
        {"attached_before_exec": False},
        {"boot_generation": DomainRef("other-boot")},
    ],
)
def test_incomplete_fresh_enforcement_never_promotes(
    case: Case, monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    case.create()
    original = case.backend.run_environment_verify

    async def broken(
        distribution: PythonDistributionConfiguration,
        operation_id: DomainRef,
        environment_path: Path,
        helper_sha256: str,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence:
        return (
            await original(
                distribution,
                operation_id,
                environment_path,
                helper_sha256,
                cancellation=cancellation,
            )
        ).model_copy(update=change)

    monkeypatch.setattr(case.backend, "run_environment_verify", broken)
    with pytest.raises(EnvironmentFailure):
        validate(case)
    assert case.resources.load(case.claim.resource_ref).state.value == "LOST"


@pytest.mark.parametrize("drift", ["environment", "distribution", "helper", "backend"])
def test_drift_after_promotion_invalidates_current_claim(case: Case, drift: str) -> None:
    case.create()
    validate(case)
    if drift == "environment":
        (case.path / "venv/pyvenv.cfg").write_bytes(b"changed after READY")
    elif drift == "distribution":
        (case.provider.distribution.distribution_root / "lib/python3.12/os.py").write_bytes(
            b"changed after READY"
        )
    elif drift == "helper":
        case.provider.helper_sha256 = "0" * 64
    else:
        case.provider.backend_identity = case.provider.backend_identity.model_copy(
            update={"binary_sha256": "0" * 64}
        )
    with pytest.raises(EnvironmentFailure):
        PythonRevalidationRepository(case.provider).current(case.claim.resource_ref)
    assert case.resources.load(case.claim.resource_ref).state.value == "LOST"
    assert len(PythonRevalidationRepository(case.provider).history(case.claim.resource_ref)) == 1


def test_forward_upgrade_retains_e5e_construction_and_immutable_rows(
    case: Case, tmp_path: Path
) -> None:
    from boberagent_execution_node.persistence import RuntimeDatabase
    from boberagent_execution_node.persistence.migrations import current_revision, upgrade_database
    from boberagent_execution_node.persistence.orm import Base

    construction = case.create()
    legacy = RuntimeDatabase(tmp_path / "legacy-e5e.sqlite3")
    upgrade_database(legacy, "0011_empty_python_environment")
    # Seed the old schema through SQL, never run the current ORM against old columns.
    # The owned fixture is UNCHECKED and not READY; no authority/history is forged for use.
    try:
        with legacy.transaction() as destination, case.database.transaction() as source:
            existing = {
                r[0]
                for r in destination.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            }
            for table in Base.metadata.sorted_tables:
                name = table.name
                if name not in existing:
                    continue
                columns = [r[1] for r in destination.execute(text(f"PRAGMA table_info({name})"))]
                rows = source.execute(text(f"SELECT {','.join(columns)} FROM {name}")).mappings()
                for row in rows:
                    values = dict(row)
                    if name == "python_resource_details":
                        values["phase"] = "RESERVED"
                    destination.execute(
                        text(
                            f"INSERT INTO {name} ({','.join(columns)}) VALUES ({','.join(':' + c for c in columns)})"
                        ),
                        values,
                    )
            destination.execute(text("UPDATE python_resource_details SET phase='VERIFYING'"))
        upgrade_database(legacy)
        assert current_revision(legacy) == "0012_python_revalidation"
        resources = PythonResourceRepository(
            legacy, node_id="node-test", boot_generation=DomainRef("boot-new"), clock=lambda: NOW
        )
        repository = PythonEnvironmentRepository(resources, case.repository.storage)
        assert repository.inspect_retained(case.claim.resource_ref) == construction
        assert resources.load(case.claim.resource_ref).validity.value == "UNCHECKED"
        with legacy.transaction() as session:
            assert session.execute(text("PRAGMA foreign_key_check")).first() is None
        with pytest.raises(IntegrityError), legacy.transaction() as session:
            runtime_row = session.get(RuntimeResourceRow, str(case.claim.resource_ref))
            assert runtime_row is not None
            runtime_row.state = "READY"
            session.flush()
    finally:
        legacy.close()
