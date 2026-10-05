"""E5-B SQLite ownership tests: synthetic retained metadata, no source/runtime bytes."""

import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from boberagent_contracts import (
    DomainRef,
    PreparationReasonCode,
    PythonProviderOperation,
    PythonProviderPhase,
    PythonResourceState,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeFailure,
    PythonRuntimeValidity,
    ResourceRef,
    python_runtime_request_digest,
)
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.persistence import RuntimeDatabase, RuntimeStore
from boberagent_execution_node.persistence.migrations import current_revision, upgrade_database
from boberagent_execution_node.persistence.orm import (
    ImportedArtifactRow,
    PreparationAuthorityRow,
    PreparationImportRow,
    PreparationMaterializationRow,
    PythonResourceRow,
    RunRow,
    RuntimeResourceRow,
)
from boberagent_execution_node.preparation.resource_models import (
    BudgetAmount,
    BudgetCategory,
    CleanupState,
    OperationState,
    ResourceOperation,
)
from boberagent_execution_node.preparation.resources import (
    PythonResourceRepository,
    ResourceOwnershipError,
)
from boberagent_transport.preparation_materialization import (
    MaterializationEvidence,
    materialization_message_id,
)
from plan_test_fixtures import NOW
from python_runtime_test_fixtures import runtime_authority_fixture
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class CrashDatabase(RuntimeDatabase):
    """Simulate loss before commit without a production fault-injection interface."""

    fail_commit = False

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with super().transaction() as session:
            yield session
            if self.fail_commit:
                self.fail_commit = False
                raise RuntimeError("simulated crash before commit")


def _seed(database: RuntimeDatabase, authority: PythonRuntimeAuthorityProjection) -> None:
    permit, binding = authority.permit, authority.binding
    source = permit.spec.source.plan_source
    evidence = MaterializationEvidence(
        request_message_id=materialization_message_id(permit.permit_ref),
        node_id=permit.spec.node_id,
        preparation_ref=permit.spec.preparation_ref,
        permit_ref=permit.permit_ref,
        permit_sha256=binding.permit_sha256,
        run_ref=permit.run_ref,
        mission_ref=permit.spec.mission_ref,
        plan_ref=permit.spec.plan_ref,
        plan_intent_sha256=permit.spec.plan_intent_sha256,
        raw_artifact_ref=source.raw_artifact_ref,
        raw_sha256=source.raw_sha256,
        manifest_artifact_ref=source.manifest_artifact_ref,
        manifest_sha256=source.manifest_sha256,
        materialization_id=binding.materialization_id,
        file_count=1,
        verified_entry_count=1,
        materialized_bytes=200,
        observed_temporary_bytes=500,
        observed_write_bytes=200,
        observed_duration_seconds=1.2,
        budgets=permit.spec.budgets,
        tree_sha256=binding.source_tree_sha256,
        confinement_backend="synthetic-e4",
        confinement_version="1",
        proven_features=(),
        started_at=NOW,
        published_at=NOW,
    )
    with database.transaction() as session:
        session.add(
            RunRow(
                run_id=str(permit.run_ref),
                mission_id=str(permit.spec.mission_ref),
                capability_id="runtime.prepare",
                operation="prepare",
                status="QUEUED",
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            PreparationAuthorityRow(
                permit_id=str(permit.permit_ref),
                preparation_id=str(permit.spec.preparation_ref),
                run_id=str(permit.run_ref),
                authority_sha256=binding.permit_sha256,
                principal_id="core-test",
                permit_json=permit.model_dump(mode="json"),
                admitted_at=NOW,
            )
        )
        session.flush()
        session.add(
            PreparationMaterializationRow(
                preparation_id=str(permit.spec.preparation_ref),
                permit_id=str(permit.permit_ref),
                run_id=str(permit.run_ref),
                materialization_id=str(binding.materialization_id),
                state="PUBLISHED",
                evidence_json=evidence.model_dump(mode="json"),
                error_code=None,
                started_at=NOW,
                updated_at=NOW,
            )
        )
        for ref, digest, size in (
            (source.raw_artifact_ref, source.raw_sha256, source.raw_size_bytes),
            (
                source.manifest_artifact_ref,
                source.manifest_sha256,
                permit.spec.source.manifest_size_bytes,
            ),
        ):
            session.add(
                ImportedArtifactRow(
                    artifact_id=str(ref),
                    sha256=digest,
                    size_bytes=size,
                    content_key=digest,
                    verified_at=NOW,
                )
            )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[CrashDatabase]:
    database = CrashDatabase(tmp_path / "runtime.sqlite3")
    upgrade_database(database)
    _seed(database, runtime_authority_fixture())
    yield database
    database.close()


def _repo(
    database: RuntimeDatabase, boot: str = "boot-a", offset: int = 0
) -> PythonResourceRepository:
    return PythonResourceRepository(
        database,
        node_id="node-test",
        boot_generation=DomainRef(boot),
        clock=lambda: NOW + timedelta(seconds=offset),
    )


def _reserve(repository: PythonResourceRepository) -> ResourceRef:
    return repository.reserve(runtime_authority_fixture(), principal_id="core-test").resource_ref


def _claim(
    repository: PythonResourceRepository,
    ref: ResourceRef,
    name: str = "operation-a",
    operation: PythonProviderOperation = PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT,
    owner: str = "owner-a",
) -> ResourceOperation:
    return repository.claim(
        ref,
        operation_id=DomainRef(name),
        operation=operation,
        owner_token=DomainRef(owner),
        principal_id="core-test",
    )


def _amount(
    amount: int, category: BudgetCategory = BudgetCategory.OUTPUT_BYTES
) -> tuple[BudgetAmount, ...]:
    return (BudgetAmount(category=category, amount=amount),)


def test_reservation_reopen_identity_and_source_retention(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    value = repo.load(ref)
    assert value.phase is PythonProviderPhase.RESERVED
    assert value.state is PythonResourceState.CREATING
    assert value.validity is PythonRuntimeValidity.UNCHECKED
    assert value.request_sha256 == python_runtime_request_digest(
        runtime_authority_fixture().binding
    )
    assert repo.find_by_binding(value.request_sha256) == value
    assert _reserve(repo) == ref
    descriptor = RuntimeStore(database).get_resource(ref)
    assert descriptor is not None
    assert descriptor.descriptor.provider == "python-stdlib@1"
    assert descriptor.descriptor.owner_ref == value.request.spec.mission_ref
    assert descriptor.descriptor.created_by_run == value.request.run_ref
    database.close()
    reopened = RuntimeDatabase(database.path)
    try:
        other = _repo(reopened, "boot-b")
        assert other.reconcile() == 0
        assert other.load(ref) == value
        assert _reserve(other) == ref
        with reopened.transaction() as session:
            assert session.scalar(select(func.count()).select_from(RuntimeResourceRow)) == 1
            assert session.scalar(select(func.count()).select_from(RunRow)) == 1
            materialization = session.get(PreparationMaterializationRow, "preparation-test")
            assert materialization is not None and materialization.state == "PUBLISHED"
        with pytest.raises(IntegrityError), reopened.transaction() as session:
            materialization = session.get(PreparationMaterializationRow, "preparation-test")
            assert materialization is not None
            session.delete(materialization)
            session.flush()
    finally:
        reopened.close()


def test_concurrent_identical_reservation_one_resource(database: CrashDatabase) -> None:
    barrier = Barrier(4)

    def reserve(_: int) -> ResourceRef:
        barrier.wait()
        return _reserve(_repo(database))

    with ThreadPoolExecutor(max_workers=4) as pool:
        refs = list(pool.map(reserve, range(4)))
    assert len(set(refs)) == 1
    assert RuntimeStore(database).runtime_resource_count() == 1


def test_canonical_declared_set_order_reuses_binding_without_rewriting_history(
    database: CrashDatabase,
) -> None:
    repo = _repo(database)
    original = runtime_authority_fixture()
    reserved = repo.reserve(original, principal_id="core-test")
    reordered_spec = original.permit.spec.model_copy(
        update={
            "allowed_actions": tuple(reversed(original.permit.spec.allowed_actions)),
        }
    )
    reordered = PythonRuntimeAuthorityProjection(
        permit=original.permit.model_copy(update={"spec": reordered_spec}),
        binding=original.binding.model_copy(update={"spec": reordered_spec}),
    )
    assert python_runtime_request_digest(reordered.binding) == reserved.request_sha256
    assert repo.reserve(reordered, principal_id="core-test") == reserved
    assert repo.load(reserved.resource_ref).request == original.binding


@pytest.mark.parametrize("field", ["materialization_id", "source_tree_sha256"])
def test_conflicting_binding_cannot_rewrite_reservation(
    database: CrashDatabase, field: str
) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    before = repo.load(ref)
    data = runtime_authority_fixture().model_dump(mode="json")
    binding = data["binding"]
    assert isinstance(binding, dict)
    binding[field] = "different-materialization" if field == "materialization_id" else "f" * 64
    conflict = PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))
    with pytest.raises(ResourceOwnershipError, match="binding conflict"):
        repo.reserve(conflict, principal_id="core-test")
    assert repo.load(ref) == before


def test_unadmitted_wrong_principal_and_e4_mismatch_reject(database: CrashDatabase) -> None:
    repo = _repo(database)
    with pytest.raises(ResourceOwnershipError, match="admitted authority"):
        repo.reserve(runtime_authority_fixture(), principal_id="untrusted")
    with database.transaction() as session:
        row = session.get(PreparationMaterializationRow, "preparation-test")
        assert row is not None
        row.state = "QUARANTINED"
    with pytest.raises(ResourceOwnershipError, match="published E4 metadata"):
        _reserve(repo)
    assert RuntimeStore(database).runtime_resource_count() == 0


def test_exclusive_claim_replay_conflict_and_generation(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    first = _claim(repo, ref)
    assert first == _claim(repo, ref)
    with pytest.raises(ResourceOwnershipError, match="different ownership"):
        _claim(repo, ref, owner="owner-b")
    with pytest.raises(ResourceOwnershipError, match="exclusive owner"):
        _claim(repo, ref, name="operation-b")
    assert repo.release_claim(first).state is OperationState.RELEASED
    assert repo.release_claim(first).state is OperationState.RELEASED
    second = _claim(repo, ref, name="operation-b")
    assert second.generation == first.generation + 1
    with pytest.raises(ResourceOwnershipError, match="stale or inactive"):
        repo.mark_building(first)


def test_concurrent_exclusive_owners(database: CrashDatabase) -> None:
    ref = _reserve(_repo(database))
    barrier = Barrier(2)

    def claim(name: str) -> ResourceOperation | None:
        barrier.wait()
        try:
            return _claim(_repo(database), ref, name=name, owner=name)
        except ResourceOwnershipError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("owner-a", "owner-b")))
    assert sum(value is not None for value in results) == 1
    assert len(_repo(database).operations(ref)) == 1


def test_stale_owner_not_stolen_and_expiry_cleanup_allowed(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    old = _claim(repo, ref)
    stale = _repo(database, offset=61)
    with pytest.raises(ResourceOwnershipError, match="never steal"):
        _claim(stale, ref, name="new-owner")
    assert stale.reconcile() == 1
    assert stale.reconcile() == 0
    assert stale.operations(ref)[0].state is OperationState.INTERRUPTED
    with pytest.raises(ResourceOwnershipError, match="stale or inactive"):
        stale.mark_building(old)
    expired = _repo(database, offset=3601)
    assert _reserve(expired) == ref  # history only
    cleanup = _claim(expired, ref, name="cleanup", operation=PythonProviderOperation.RELEASE)
    expired.begin_cleanup(cleanup)
    assert expired.complete_cleanup(cleanup).state is PythonResourceState.CLOSED


def test_expired_permit_denies_new_reservation_and_build_claim(database: CrashDatabase) -> None:
    expired = _repo(database, offset=3601)
    with pytest.raises(ResourceOwnershipError) as failure:
        _reserve(expired)
    assert failure.value.code is PreparationReasonCode.AUTHORITY_STALE
    ref = _reserve(_repo(database))
    with pytest.raises(ResourceOwnershipError) as failure:
        _claim(expired, ref)
    assert failure.value.code is PreparationReasonCode.AUTHORITY_STALE


def test_budget_seed_reserve_settle_and_conflicting_replay(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    balances = {entry.category: entry for entry in repo.budget(ref)}
    assert balances[BudgetCategory.IMPORTED_BYTES].committed == 300
    assert balances[BudgetCategory.MATERIALIZED_BYTES].committed == 200
    assert balances[BudgetCategory.TOTAL_SECONDS].committed == 2
    claim = _claim(repo, ref)
    repo.reserve_budget(claim, _amount(900))
    repo.reserve_budget(claim, _amount(900))
    with pytest.raises(ResourceOwnershipError, match="reservation replay changed"):
        repo.reserve_budget(claim, _amount(901))
    with pytest.raises(ResourceOwnershipError, match="exceeds reservation"):
        repo.settle_budget(claim, _amount(901))
    repo.settle_budget(claim, _amount(800))
    repo.settle_budget(claim, _amount(800))
    repo.release_claim(claim)
    with pytest.raises(ResourceOwnershipError, match="history cannot change"):
        repo.settle_budget(claim, _amount(700))
    second = _claim(repo, ref, name="operation-b")
    with pytest.raises(ResourceOwnershipError, match="budget exhausted"):
        repo.reserve_budget(second, _amount(201))
    repo.reserve_budget(second, _amount(200))
    repo.settle_budget(second, _amount(200))
    assert {entry.category: entry for entry in repo.budget(ref)}[
        BudgetCategory.OUTPUT_BYTES
    ].available == 0


def test_retained_import_elapsed_budget_survives_reservation_reopen(
    database: CrashDatabase,
) -> None:
    source = runtime_authority_fixture().permit.spec.source.plan_source
    with database.transaction() as session:
        session.add(
            PreparationImportRow(
                import_id="import-retained",
                permit_id="permit-test",
                artifact_id=str(source.raw_artifact_ref),
                sha256=source.raw_sha256,
                size_bytes=source.raw_size_bytes,
                received_bytes=source.raw_size_bytes,
                state="VERIFIED",
                started_at=NOW - timedelta(seconds=4),
                updated_at=NOW,
            )
        )
    repo = _repo(database)
    ref = _reserve(repo)
    balance = {entry.category: entry for entry in repo.budget(ref)}[BudgetCategory.TOTAL_SECONDS]
    assert balance.committed == 6 and balance.available == 54
    assert _reserve(_repo(database, "boot-b")) == ref
    assert _repo(database, "boot-b").budget(ref) == repo.budget(ref)


def test_budget_concurrency_and_interruption_never_refunds(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    claim = _claim(repo, ref)
    barrier = Barrier(2)

    def reserve(amount: int) -> bool:
        barrier.wait()
        try:
            _repo(database).reserve_budget(claim, _amount(amount))
            return True
        except ResourceOwnershipError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, (800, 900)))
    assert sorted(outcomes) == [False, True]
    before = {entry.category: entry for entry in repo.budget(ref)}[BudgetCategory.OUTPUT_BYTES]
    assert before.held in {800, 900}
    assert _repo(database, "boot-b").reconcile() == 1
    after = {entry.category: entry for entry in repo.budget(ref)}[BudgetCategory.OUTPUT_BYTES]
    assert after.committed == before.held and after.held == 0
    assert after.available == before.available
    with pytest.raises(ResourceOwnershipError, match="history cannot change"):
        repo.settle_budget(claim, _amount(0))
    assert repo.load(ref).phase is PythonProviderPhase.QUARANTINED


def test_peak_budget_retains_max_without_summing_sequential_peaks(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    for index in range(2):
        claim = _claim(repo, ref, name=f"operation-{index}")
        repo.reserve_budget(claim, _amount(2, BudgetCategory.PROCESSES))
        repo.settle_budget(claim, _amount(1, BudgetCategory.PROCESSES))
        repo.release_claim(claim)
    peak = {entry.category: entry for entry in repo.budget(ref)}[BudgetCategory.PROCESSES]
    assert peak.committed == 1 and peak.limit == 2


@pytest.mark.parametrize("category", list(BudgetCategory))
def test_each_exact_budget_category_rejects_overspend(
    database: CrashDatabase, category: BudgetCategory
) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    claim = _claim(repo, ref)
    balance = {value.category: value for value in repo.budget(ref)}[category]
    with pytest.raises(ResourceOwnershipError, match="budget exhausted"):
        repo.reserve_budget(claim, _amount(balance.available + 1, category))
    assert repo.budget(ref) == _repo(database).budget(ref)
    repo.reserve_budget(claim, _amount(balance.available, category))
    assert {value.category: value for value in repo.budget(ref)}[category].available == 0


def test_released_build_metadata_reopen_is_not_resumed(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    claim = _claim(repo, ref)
    repo.mark_building(claim)
    repo.release_claim(claim)
    recovered = _repo(database, "boot-b")
    assert recovered.reconcile() == 1
    assert recovered.load(ref).state is PythonResourceState.LOST
    assert recovered.operations(ref)[0].state is OperationState.RELEASED


def test_conflicting_concurrent_binding_preserves_committed_identity(
    database: CrashDatabase,
) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    expected = repo.load(ref)
    barrier = Barrier(2)
    data = runtime_authority_fixture().model_dump(mode="json")
    data["binding"]["source_tree_sha256"] = "f" * 64
    different = PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))

    def reserve(authority: PythonRuntimeAuthorityProjection) -> bool:
        barrier.wait()
        try:
            _repo(database).reserve(authority, principal_id="core-test")
            return True
        except ResourceOwnershipError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(reserve, (runtime_authority_fixture(), different))) == [True, False]
    assert _repo(database, "boot-b").load(ref) == expected


@pytest.mark.parametrize(
    "stage", ["reservation", "claim", "building", "quarantine", "cleanup", "cleanup-completion"]
)
def test_crash_before_metadata_commit_rolls_back(database: CrashDatabase, stage: str) -> None:
    repo = _repo(database)
    if stage == "reservation":
        database.fail_commit = True
        with pytest.raises(RuntimeError, match="simulated crash"):
            _reserve(repo)
        assert RuntimeStore(database).runtime_resource_count() == 0
        assert _reserve(repo) == _reserve(repo)
        return
    ref = _reserve(repo)
    before = repo.load(ref)
    if stage == "claim":
        database.fail_commit = True
        with pytest.raises(RuntimeError):
            _claim(repo, ref)
        assert repo.load(ref) == before and not repo.operations(ref)
        return
    operation = (
        PythonProviderOperation.RELEASE
        if stage.startswith("cleanup")
        else PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT
    )
    claim = _claim(repo, ref, operation=operation)
    if stage == "cleanup-completion":
        repo.begin_cleanup(claim)
    before = repo.load(ref)
    database.fail_commit = True
    with pytest.raises(RuntimeError):
        if stage == "building":
            repo.mark_building(claim)
        elif stage == "quarantine":
            repo.quarantine(
                ref, PythonRuntimeFailure(reason_code=PreparationReasonCode.PREPARATION_INTERRUPTED)
            )
        elif stage == "cleanup":
            repo.begin_cleanup(claim)
        else:
            repo.complete_cleanup(claim)
    assert repo.load(ref) == before
    assert _repo(database, "boot-b").reconcile() == 1
    assert repo.load(ref).phase is PythonProviderPhase.QUARANTINED


@pytest.mark.parametrize("stage", ["claim", "building", "cleanup"])
def test_restart_after_commit_abandons_owner_not_identity(
    database: CrashDatabase, stage: str
) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    claim = _claim(
        repo,
        ref,
        operation=PythonProviderOperation.RELEASE
        if stage == "cleanup"
        else PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT,
    )
    if stage == "building":
        repo.mark_building(claim)
    if stage == "cleanup":
        repo.begin_cleanup(claim)
    before = repo.load(ref)
    database.close()
    reopened = RuntimeDatabase(database.path)
    try:
        recovered = _repo(reopened, "boot-b")
        assert recovered.reconcile() == 1
        after = recovered.load(ref)
        assert after.request == before.request and after.resource_ref == before.resource_ref
        assert after.validity is PythonRuntimeValidity.UNCHECKED
        assert after.phase is PythonProviderPhase.QUARANTINED
        assert after.failure is not None
        assert after.state is (
            PythonResourceState.CLOSING if stage == "cleanup" else PythonResourceState.LOST
        )
        assert recovered.operations(ref)[0].state is OperationState.INTERRUPTED
        if stage == "cleanup":
            assert after.cleanup is CleanupState.FAILED
            cleanup = _claim(
                recovered, ref, name="cleanup-recovery", operation=PythonProviderOperation.RELEASE
            )
            recovered.begin_cleanup(cleanup)
            recovered.complete_cleanup(cleanup)
        else:
            with pytest.raises(ResourceOwnershipError, match="unavailable"):
                _claim(recovered, ref, name="no-rebuild")
    finally:
        reopened.close()


def test_cleanup_failure_and_lost_completion_ack_replay(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    cleanup = _claim(repo, ref, operation=PythonProviderOperation.RELEASE)
    repo.begin_cleanup(cleanup)
    failure = PythonRuntimeFailure(reason_code=PreparationReasonCode.STORAGE_UNAVAILABLE)
    failed = repo.fail_cleanup(cleanup, failure)
    assert failed.cleanup is CleanupState.FAILED and failed.state is PythonResourceState.CLOSING
    assert failed.failure == failure
    second = _claim(repo, ref, name="cleanup-b", operation=PythonProviderOperation.RELEASE)
    repo.begin_cleanup(second)
    closed = repo.complete_cleanup(second)
    database.close()
    reopened = RuntimeDatabase(database.path)
    try:
        recovered = _repo(reopened, "boot-b")
        assert recovered.reconcile() == 0
        assert recovered.complete_cleanup(second) == closed  # lost acknowledgement, history only
        assert recovered.load(ref).failure == failure
        assert recovered.operations(ref)[0].failure == failure
    finally:
        reopened.close()


def test_ready_and_immutable_binding_database_guards(database: CrashDatabase) -> None:
    repo = _repo(database)
    ref = _reserve(repo)
    with pytest.raises(ValueError, match="typed ownership"):
        from boberagent_execution_node.persistence import ResourceRuntimeState

        RuntimeStore(database).update_resource_state(ref, ResourceRuntimeState.READY, NOW)
    with pytest.raises(IntegrityError, match="cannot be READY"), database.transaction() as session:
        resource = session.get(RuntimeResourceRow, str(ref))
        assert resource is not None
        resource.state = "READY"
    with pytest.raises(IntegrityError, match="immutable"), database.transaction() as session:
        detail = session.get(PythonResourceRow, str(ref))
        assert detail is not None
        detail.request_sha256 = "f" * 64
    assert repo.load(ref).state is PythonResourceState.CREATING


def test_upgrade_e4_and_idempotent_head_preserve_metadata(tmp_path: Path) -> None:
    database = RuntimeDatabase(tmp_path / "upgrade.sqlite3")
    try:
        upgrade_database(database, "0007_preparation_materialization")
        _seed(database, runtime_authority_fixture())
        with database.transaction() as session:
            old = session.get(PreparationMaterializationRow, "preparation-test")
            assert old is not None
            evidence = old.evidence_json
        upgrade_database(database)
        upgrade_database(database)
        assert current_revision(database) == "0010_python_provenance"
        assert {
            "python_resource_details",
            "python_resource_operations",
            "python_resource_budget_entries",
        } <= set(inspect(database.migration_engine).get_table_names())
        with database.transaction() as session:
            row = session.get(PreparationMaterializationRow, "preparation-test")
            assert row is not None and row.evidence_json == evidence
            assert session.scalar(select(func.count()).select_from(ImportedArtifactRow)) == 2
        assert _reserve(_repo(database))
    finally:
        database.close()


def test_real_node_startup_reconciles_metadata_without_provider_or_workspace(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        configuration = NodeConfiguration.for_runtime_directory(
            tmp_path / "node", configured_node_id="node-test"
        )
        node = ExecutionNode(configuration)
        await node.initialize()
        assert node.database is not None and node.identity is not None
        identity = node.identity
        _seed(node.database, runtime_authority_fixture())
        repo = _repo(node.database)
        ref = _reserve(repo)
        _claim(repo, ref)
        await node.shutdown()
        reopened = ExecutionNode(configuration)
        try:
            await reopened.initialize()
            assert reopened.identity == identity
            assert reopened.python_resources is not None
            value = reopened.python_resources.load(ref)
            assert value.phase is PythonProviderPhase.QUARANTINED
            assert value.state is PythonResourceState.LOST
            assert not tuple(configuration.workspace_root.iterdir())
            assert reopened.store is not None and reopened.store.runtime_resource_count() == 1
        finally:
            await reopened.shutdown()

    asyncio.run(scenario())
