"""Additional history and integrity adversarial cases; no evaluator or runtime services."""

from pathlib import Path

import pytest
from boberagent_contracts import ExecutionPlanV2, InteractionRef, execution_intent_digest
from boberagent_contracts.plan_values import OperatorValue
from boberagent_core import CoreDatabase, DatabaseConfig
from boberagent_core.planning import (
    ApprovalDocument,
    OperatorPlanApproval,
    PlanDecisionRecord,
    PlanDecisionRef,
    PlanningAnswer,
    PlanningDisposition,
    PlanningRequest,
    PlanPolicyAssessment,
    PlanProposalRevision,
    PolicyDocument,
)
from boberagent_core.planning import (
    PlanningAttemptLifecycle as State,
)
from boberagent_core.planning.errors import PlanningConflict, PlanningPersistenceError
from plan_test_fixtures import NOW, plan_fixture
from planning_persistence_fixtures import attempt_fixture, finalize, seed
from sqlalchemy import text
from test_planning_plan_history import decisions


def test_invalid_lifecycle_and_stale_expected_state_rejected(database: CoreDatabase) -> None:
    seed(database)
    attempt = attempt_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        for state, expected, disposition in (
            (State.WAITING_INPUT, State.REQUESTED, PlanningDisposition.REQUIRES_INPUT),
            (State.EVALUATING, State.WAITING_INPUT, None),
            (State.COMPLETED, State.REQUESTED, PlanningDisposition.VALID),
        ):
            with pytest.raises(PlanningConflict):
                work.planning_attempts.update_lifecycle(
                    attempt.planning_attempt_ref,
                    state,
                    expected_state=expected,
                    expected_revision=0,
                    updated_at=NOW,
                    disposition=disposition,
                )
        assert work.planning_attempts.get(attempt.planning_attempt_ref) == attempt


def test_changed_intent_cannot_overwrite_existing_plan_identity(database: CoreDatabase) -> None:
    seed(database)
    plan = plan_fixture()
    finalize(database, attempt_fixture(), plan)
    changed = ExecutionPlanV2.model_validate(
        {
            **plan.model_dump(),
            "invocation": {
                **plan.invocation.model_dump(),
                "arguments": tuple(reversed(plan.invocation.arguments)),
            },
        }
    )
    request = PlanningRequest.model_validate(
        {**attempt_fixture().request.model_dump(), "policy_version": "2"}
    )
    second = attempt_fixture("planning-conflicting-plan", request=request)
    with database.unit_of_work() as work:
        work.planning_attempts.add(second)
        with pytest.raises(PlanningConflict):
            work.planning_attempts.finalize(
                second.planning_attempt_ref,
                changed,
                intent_sha256=execution_intent_digest(changed),
                expected_state=State.REQUESTED,
                expected_revision=0,
                completed_at=NOW,
            )
        original = work.execution_plans.get(plan.execution_plan_id)
        assert original is not None and original.plan == plan
        assert work.planning_attempts.get(second.planning_attempt_ref) == second


def test_proposal_answer_provenance_retained_without_interactions(
    database: CoreDatabase, database_path: Path
) -> None:
    seed(database)
    attempt = attempt_fixture()
    answer = PlanningAnswer(
        answer_id="answer-d2",
        interaction_ref=InteractionRef("future-d6-ref"),
        planning_attempt_ref=attempt.planning_attempt_ref,
        parameter_id="mode",
        operator_id="operator-d2",
        value=OperatorValue(answer_id="answer-d2", value="check"),
        answered_at=NOW,
    )
    assert attempt.request.proposal is not None
    revision = PlanProposalRevision(
        planning_attempt_ref=attempt.planning_attempt_ref,
        revision_number=1,
        proposal=attempt.request.proposal,
        answers=(answer,),
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        work.planning_attempts.update_proposal(
            revision, expected_state=State.REQUESTED, expected_revision=0
        )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        with reopened.unit_of_work() as work:
            stored = work.planning_attempts.get(attempt.planning_attempt_ref)
            assert stored is not None and stored.revisions[0].answers == (answer,)
        with reopened._migration_engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM interactions")).scalar_one() == 0
    finally:
        reopened.dispose()


def test_restart_does_not_implicitly_recover_evaluating(
    database: CoreDatabase, database_path: Path
) -> None:
    seed(database)
    attempt = attempt_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
        evaluating = work.planning_attempts.update_lifecycle(
            attempt.planning_attempt_ref,
            State.EVALUATING,
            expected_state=State.REQUESTED,
            expected_revision=0,
            updated_at=NOW,
        )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        with reopened.unit_of_work() as work:
            assert work.planning_attempts.get(attempt.planning_attempt_ref) == evaluating
            assert (
                work.planning_attempts.recover_unproven_active_attempts(
                    cutoff=NOW, recovered_at=NOW
                )
                == 1
            )
            recovered = work.planning_attempts.get(attempt.planning_attempt_ref)
            assert recovered is not None and recovered.lifecycle is State.INTERRUPTED
    finally:
        reopened.dispose()


def test_all_policy_and_operator_history_variants_retained(database: CoreDatabase) -> None:
    seed(database)
    finalize(database, attempt_fixture())
    baseline = decisions()
    records = [baseline[1], baseline[2]]
    for value in ("DENY", "REQUIRES_APPROVAL", "NOT_EVALUATED"):
        policy = PlanPolicyAssessment.model_validate(
            {**baseline[1].document.value.model_dump(), "decision": value}
        )
        records.append(
            PlanDecisionRecord(
                decision_ref=PlanDecisionRef("policy-" + value),
                document=PolicyDocument(value=policy),
                context=baseline[1].context,
                created_at=NOW,
            )
        )
    rejection = OperatorPlanApproval.model_validate(
        {**baseline[2].document.value.model_dump(), "decision": "REJECT"}
    )
    records.append(
        PlanDecisionRecord(
            decision_ref=PlanDecisionRef("operator-reject"),
            document=ApprovalDocument(value=rejection),
            context=baseline[2].context,
            created_at=NOW,
        )
    )
    with database.unit_of_work() as work:
        for record in records:
            work.plan_decisions.append(record)
        loaded = work.plan_decisions.list_for_plan(plan_fixture().execution_plan_id)
        assert {record.decision_ref for record in loaded} == {
            record.decision_ref for record in records
        }
        assert all(work.plan_decisions.get(record.decision_ref) == record for record in records)


@pytest.mark.parametrize("table", ["planning_attempts", "execution_plans", "plan_decisions"])
@pytest.mark.parametrize("content", ["not-json-sensitive-placeholder", "[]", "null", "42"])
def test_invalid_json_syntax_raises_safe_repository_error(
    database: CoreDatabase, table: str, content: str
) -> None:
    seed(database)
    attempt = attempt_fixture()
    finalize(database, attempt)
    with database.unit_of_work() as work:
        work.plan_decisions.append(decisions()[0])
    trigger = (
        "planning_attempt_terminal" if table == "planning_attempts" else table + "_immutable_update"
    )
    column = {
        "planning_attempts": "request_json",
        "execution_plans": "plan_json",
        "plan_decisions": "record_json",
    }[table]
    with database._migration_engine.begin() as connection:
        connection.execute(text(f"DROP TRIGGER {trigger}"))
        if table == "planning_attempts":
            connection.execute(text("DROP TRIGGER planning_attempt_identity"))
        connection.execute(
            text(f"UPDATE {table} SET {column} = :value"),
            {"value": content},
        )
    with database.unit_of_work() as work, pytest.raises(PlanningPersistenceError) as raised:
        if table == "planning_attempts":
            work.planning_attempts.get(attempt.planning_attempt_ref)
        elif table == "execution_plans":
            work.execution_plans.get_by_intent_digest(execution_intent_digest(plan_fixture()))
        else:
            work.plan_decisions.list_for_plan(plan_fixture().execution_plan_id)
    assert "sensitive-placeholder" not in str(raised.value)
