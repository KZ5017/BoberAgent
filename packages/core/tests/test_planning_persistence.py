"""Migration-backed D2 history, revisions, restart and database-level atomic reuse."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from boberagent_contracts import ExecutionPlanRef, execution_intent_digest
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_core import CoreDatabase, DatabaseConfig
from boberagent_core.inspections.classification_models import SupportClassification
from boberagent_core.planning import (
    PlanningAttemptLifecycle as State,
)
from boberagent_core.planning import (
    PlanningAttemptRef,
    PlanningRequest,
    PlanProposal,
    PlanProposalRevision,
    planning_request_fingerprint,
)
from boberagent_core.planning import (
    PlanningDisposition as Disposition,
)
from boberagent_core.planning.errors import PlanningConflict, PlanningPersistenceError
from plan_test_fixtures import NOW, plan_fixture
from planning_persistence_fixtures import attempt_fixture, finalize, seed
from sqlalchemy import text


def test_attempt_round_trip_fingerprint_and_c3_pins(database: CoreDatabase) -> None:
    seed(database)
    attempt = attempt_fixture()
    with database.unit_of_work() as work:
        assert work.planning_attempts.add(attempt) == attempt
        assert work.planning_attempts.get(attempt.planning_attempt_ref) == attempt
        assert (
            work.planning_attempts.find_reusable_by_fingerprint(
                planning_request_fingerprint(attempt.request)
            )
            == attempt
        )
    with database._migration_engine.connect() as connection:
        row = connection.execute(
            text("SELECT semantic_sha256, classification_sha256 FROM planning_attempts")
        ).one()
    assert row.semantic_sha256 == "e" * 64
    assert row.classification_sha256 == canonical_digest(attempt.request.inspection.classification)
    assert row.semantic_sha256 != row.classification_sha256


@pytest.mark.parametrize(
    "state", [State.REQUESTED, State.EVALUATING, State.WAITING_INPUT, State.COMPLETED]
)
def test_equivalent_active_and_completed_reuse(database: CoreDatabase, state: State) -> None:
    seed(database)
    attempt = attempt_fixture()
    if state is State.COMPLETED:
        finalize(database, attempt)
    else:
        with database.unit_of_work() as work:
            work.planning_attempts.add(attempt)
            if state is not State.REQUESTED:
                work.planning_attempts.update_lifecycle(
                    attempt.planning_attempt_ref,
                    State.EVALUATING,
                    expected_state=State.REQUESTED,
                    expected_revision=0,
                    updated_at=NOW,
                )
            if state is State.WAITING_INPUT:
                work.planning_attempts.update_lifecycle(
                    attempt.planning_attempt_ref,
                    state,
                    expected_state=State.EVALUATING,
                    expected_revision=0,
                    updated_at=NOW,
                    disposition=Disposition.REQUIRES_INPUT,
                )
    with database.unit_of_work() as work:
        reused = work.planning_attempts.add(attempt_fixture("planning-other-id"))
        assert reused.planning_attempt_ref == attempt.planning_attempt_ref
        assert reused.lifecycle is state
        changed = PlanningRequest.model_validate(
            {**attempt.request.model_dump(), "policy_version": "2"}
        )
        different = work.planning_attempts.add(
            attempt_fixture("planning-different", request=changed)
        )
        assert different.planning_attempt_ref != reused.planning_attempt_ref
        with pytest.raises(PlanningConflict):
            work.planning_attempts.add(
                attempt_fixture(str(attempt.planning_attempt_ref), request=changed)
            )


@pytest.mark.parametrize("state", [State.FAILED, State.INTERRUPTED, State.CANCELLED])
def test_unsuccessful_history_deliberate_new_request(database: CoreDatabase, state: State) -> None:
    seed(database)
    attempt = attempt_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        work.planning_attempts.update_lifecycle(
            attempt.planning_attempt_ref,
            State.EVALUATING,
            expected_state=State.REQUESTED,
            expected_revision=0,
            updated_at=NOW,
        )
        terminal = work.planning_attempts.update_lifecycle(
            attempt.planning_attempt_ref,
            state,
            expected_state=State.EVALUATING,
            expected_revision=0,
            updated_at=NOW,
            failure_code="TEST_FAILURE",
        )
        assert terminal.completed_at == NOW
        assert (
            work.planning_attempts.find_reusable_by_fingerprint(
                planning_request_fingerprint(attempt.request)
            )
            is None
        )
        with pytest.raises(PlanningConflict):
            work.planning_attempts.update_lifecycle(
                attempt.planning_attempt_ref,
                State.EVALUATING,
                expected_state=state,
                expected_revision=0,
                updated_at=NOW,
            )
        retry = work.planning_attempts.add(attempt_fixture("planning-deliberate-new"))
        assert retry.planning_attempt_ref != terminal.planning_attempt_ref
        assert work.planning_attempts.get(terminal.planning_attempt_ref) == terminal


def test_proposal_chain_monotonic_cas_and_wait_survives_reopen(
    database: CoreDatabase, database_path: Path
) -> None:
    seed(database)
    attempt = attempt_fixture(classification=SupportClassification.ASSISTED)
    proposal = PlanProposal(
        source=attempt.request.source, unresolved_requirement_ids=("target-port",)
    )
    revision = PlanProposalRevision(
        planning_attempt_ref=attempt.planning_attempt_ref,
        revision_number=1,
        proposal=proposal,
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        work.planning_attempts.update_lifecycle(
            attempt.planning_attempt_ref,
            State.EVALUATING,
            expected_state=State.REQUESTED,
            expected_revision=0,
            updated_at=NOW,
        )
        revised = work.planning_attempts.update_proposal(
            revision, expected_state=State.EVALUATING, expected_revision=0
        )
        assert revised.revisions == (revision,)
        with pytest.raises(PlanningConflict):
            work.planning_attempts.update_proposal(
                revision, expected_state=State.EVALUATING, expected_revision=0
            )
        second = PlanProposalRevision(
            planning_attempt_ref=attempt.planning_attempt_ref,
            revision_number=2,
            proposal=proposal,
            previous_revision_digest=canonical_digest(revision),
            created_at=NOW,
        )
        with pytest.raises(PlanningConflict, match="stale"):
            work.planning_attempts.update_proposal(
                second, expected_state=State.EVALUATING, expected_revision=0
            )
        work.planning_attempts.update_proposal(
            second, expected_state=State.EVALUATING, expected_revision=1
        )
        waiting = work.planning_attempts.update_lifecycle(
            attempt.planning_attempt_ref,
            State.WAITING_INPUT,
            expected_state=State.EVALUATING,
            expected_revision=2,
            updated_at=NOW,
            disposition=Disposition.REQUIRES_INPUT,
        )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        with reopened.unit_of_work() as work:
            assert work.planning_attempts.get(attempt.planning_attempt_ref) == waiting
            assert waiting.revisions[-1].proposal.unresolved_requirement_ids == ("target-port",)
    finally:
        reopened.dispose()


def test_atomic_creation_race_independent_units_of_work(
    database: CoreDatabase, database_path: Path
) -> None:
    seed(database)
    barrier = Barrier(2)

    def create(number: int) -> PlanningAttemptRef:
        independent = CoreDatabase(DatabaseConfig.sqlite(database_path))
        try:
            with independent.unit_of_work() as work:
                barrier.wait(timeout=10)
                return work.planning_attempts.add(
                    attempt_fixture(f"planning-race-{number}")
                ).planning_attempt_ref
        finally:
            independent.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        refs = tuple(pool.map(create, (1, 2)))
    assert refs[0] == refs[1]
    with database._migration_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM planning_attempts")).scalar_one() == 1


@pytest.mark.parametrize("disposition", [Disposition.UNSUPPORTED, Disposition.INVALID])
def test_negative_determination_durable_reusable_without_plan(
    database: CoreDatabase, database_path: Path, disposition: Disposition
) -> None:
    seed(database)
    attempt = attempt_fixture(
        classification=SupportClassification.UNSUPPORTED
        if disposition is Disposition.UNSUPPORTED
        else SupportClassification.AUTOMATIC
    )
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        completed = work.planning_attempts.update_lifecycle(
            attempt.planning_attempt_ref,
            State.COMPLETED,
            expected_state=State.REQUESTED,
            expected_revision=0,
            updated_at=NOW,
            disposition=disposition,
            diagnostic_codes=("C3_BLOCKER",),
        )
        assert completed.finalized_plan is None
        if disposition is Disposition.UNSUPPORTED:
            assert completed.request.inspection.classification.blocking_unknown_refs == ("item-1",)
        with pytest.raises(PlanningConflict):
            work.planning_attempts.update_lifecycle(
                attempt.planning_attempt_ref,
                State.EVALUATING,
                expected_state=State.COMPLETED,
                expected_revision=0,
                updated_at=NOW,
            )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        with reopened.unit_of_work() as work:
            assert work.planning_attempts.get(attempt.planning_attempt_ref) == completed
            assert work.planning_attempts.add(attempt) == completed
            assert work.execution_plans.get_by_attempt(attempt.planning_attempt_ref) is None
    finally:
        reopened.dispose()


def test_explicit_recovery_changes_only_cutoff_evaluating(database: CoreDatabase) -> None:
    seed(database)
    attempts = []
    for number in range(5):
        request = attempt_fixture().request
        request = PlanningRequest.model_validate(
            {**request.model_dump(), "policy_version": str(number)}
        )
        attempts.append(attempt_fixture(f"planning-recovery-{number}", request=request))
    with database.unit_of_work() as work:
        for attempt in attempts:
            work.planning_attempts.add(attempt)
        for number in (1, 2, 4):
            work.planning_attempts.update_lifecycle(
                attempts[number].planning_attempt_ref,
                State.EVALUATING,
                expected_state=State.REQUESTED,
                expected_revision=0,
                updated_at=NOW + timedelta(seconds=1) if number == 4 else NOW,
            )
        waiting = work.planning_attempts.update_lifecycle(
            attempts[1].planning_attempt_ref,
            State.WAITING_INPUT,
            expected_state=State.EVALUATING,
            expected_revision=0,
            updated_at=NOW,
            disposition=Disposition.REQUIRES_INPUT,
        )
        completed = work.planning_attempts.update_lifecycle(
            attempts[3].planning_attempt_ref,
            State.COMPLETED,
            expected_state=State.REQUESTED,
            expected_revision=0,
            updated_at=NOW,
            disposition=Disposition.INVALID,
        )
        assert (
            work.planning_attempts.recover_unproven_active_attempts(cutoff=NOW, recovered_at=NOW)
            == 1
        )
        assert (
            work.planning_attempts.recover_unproven_active_attempts(cutoff=NOW, recovered_at=NOW)
            == 0
        )
        assert work.planning_attempts.get(attempts[0].planning_attempt_ref) == attempts[0]
        assert work.planning_attempts.get(attempts[1].planning_attempt_ref) == waiting
        recovered = work.planning_attempts.get(attempts[2].planning_attempt_ref)
        assert recovered is not None and recovered.lifecycle is State.INTERRUPTED
        assert work.planning_attempts.get(attempts[3].planning_attempt_ref) == completed
        recent = work.planning_attempts.get(attempts[4].planning_attempt_ref)
        assert recent is not None and recent.lifecycle is State.EVALUATING


def test_finalization_rolls_back_on_stale_revision_even_if_error_caught(
    database: CoreDatabase,
) -> None:
    seed(database)
    attempt = attempt_fixture()
    plan = plan_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        with pytest.raises(PlanningConflict, match="stale"):
            work.planning_attempts.finalize(
                attempt.planning_attempt_ref,
                plan,
                intent_sha256=execution_intent_digest(plan),
                expected_state=State.REQUESTED,
                expected_revision=1,
                completed_at=NOW,
            )
        assert work.execution_plans.get(plan.execution_plan_id) is None
        assert work.planning_attempts.get(attempt.planning_attempt_ref) == attempt
    with database.unit_of_work() as work:
        assert work.execution_plans.get(plan.execution_plan_id) is None


def test_outer_unit_of_work_rollback_does_not_commit_first_savepoint(
    database: CoreDatabase,
) -> None:
    seed(database)
    with pytest.raises(RuntimeError), database.unit_of_work() as work:
        work.planning_attempts.add(attempt_fixture())
        raise RuntimeError("deliberate outer rollback")
    with database.unit_of_work() as work:
        assert work.planning_attempts.get(PlanningAttemptRef("planning-d2")) is None
        assert work.execution_plans.get(ExecutionPlanRef("plan-d1")) is None


def test_incorrect_c3_digest_is_not_c2_parent_digest(database: CoreDatabase) -> None:
    seed(database)
    attempt = attempt_fixture()
    bad = attempt.model_copy(
        update={
            "request": attempt.request.model_copy(
                update={
                    "inspection": attempt.request.inspection.model_copy(
                        update={"classification_sha256": "e" * 64}
                    )
                }
            )
        }
    )
    with database.unit_of_work() as work, pytest.raises(PlanningPersistenceError, match="C3"):
        work.planning_attempts.add(bad)
