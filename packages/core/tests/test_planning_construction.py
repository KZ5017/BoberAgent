"""D4 durable, non-executing positive pipeline and conservative negative paths."""

from pathlib import Path

import pytest
from boberagent_contracts import execution_intent_digest
from boberagent_core import CoreDatabase
from boberagent_core.planning.construction import CoreExecutionPlanningService
from boberagent_core.planning.models import PlanningAttemptLifecycle as State
from boberagent_core.planning.models import PlanningDisposition as Disposition
from planning_construction_fixtures import prepared
from test_core_poc_acquisition import NOW


def test_positive_plan_validation_reopen_and_reuse(database: CoreDatabase, tmp_path: Path) -> None:
    chain, request = prepared(database, tmp_path)
    planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
    initial = planner.get(request.planning_attempt_ref)
    assert (
        initial is not None
        and initial.attempt.finalized_plan is None
        and initial.validation is None
    )
    result = planner.construct(request)
    assert result.attempt.lifecycle is State.COMPLETED
    assert result.attempt.disposition is Disposition.VALID
    assert result.policy == "NOT_EVALUATED" and result.execution_readiness == "NOT_ASSESSED"
    plan = result.attempt.finalized_plan
    assert plan is not None and result.validation is not None
    assert plan.source.acquisition_ref == chain.acquisition.acquisition_ref
    assert result.validation.intent_sha256 == execution_intent_digest(plan)
    assert len(result.attempt.revisions) == 1
    assert planner.construct(request) == result
    database.dispose()
    reopened = CoreDatabase(database.config)
    try:
        again = CoreExecutionPlanningService(reopened, clock=lambda: NOW)
        assert again.get(request.planning_attempt_ref) == result
        assert again.construct(request) == result
    finally:
        reopened.dispose()


@pytest.mark.parametrize("field", ["invocation", "limits", "runtime"])
def test_missing_construction_input(database: CoreDatabase, tmp_path: Path, field: str) -> None:
    _, request = prepared(database, tmp_path)
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
        request.model_copy(update={field: None})
    )
    expected = Disposition.REQUIRES_INPUT if field == "invocation" else Disposition.INVALID
    assert result.attempt.disposition is expected
    assert result.attempt.finalized_plan is None and result.validation is None
