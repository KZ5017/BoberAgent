"""Policy cannot turn an unvalidated plan or changed config into authority."""

from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.planning.models import PlanPolicyDecision
from boberagent_core.planning.policy_service import (
    CorePlanPolicyService,
    PolicyAssessmentError,
    PolicyProfileRegistry,
)
from boberagent_core.planning.records import PolicyDocument
from plan_test_fixtures import plan_fixture
from planning_persistence_fixtures import attempt_fixture, finalize, seed
from test_core_poc_acquisition import NOW
from test_planning_policy import _plan, _profile


def test_d2_finalized_plan_without_validation_cannot_be_assessed(database: CoreDatabase) -> None:
    seed(database)
    finalize(database, attempt_fixture())
    service = CorePlanPolicyService(database, PolicyProfileRegistry(()), clock=lambda: NOW)
    with pytest.raises(PolicyAssessmentError, match="VALIDATION_UNAVAILABLE"):
        service.evaluate(plan_fixture().execution_plan_id)
    with database.unit_of_work() as work:
        assert work.plan_decisions.list_for_plan(plan_fixture().execution_plan_id) == ()


def test_changed_policy_content_creates_new_history_not_an_approval(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, _ = _plan(database, tmp_path)
    allow_profile = _profile(plan, approval=False)
    allow = CorePlanPolicyService(
        database, PolicyProfileRegistry((allow_profile,)), clock=lambda: NOW
    ).evaluate(plan.execution_plan_id)
    stricter = _profile(
        plan,
        approval=True,
        maximum=plan.limits.model_copy(
            update={"wall_time_seconds": plan.limits.wall_time_seconds - 1}
        ),
    )
    deny = CorePlanPolicyService(
        database, PolicyProfileRegistry((stricter,)), clock=lambda: NOW
    ).evaluate(plan.execution_plan_id)
    assert isinstance(allow.record.document, PolicyDocument)
    assert isinstance(deny.record.document, PolicyDocument)
    assert allow.record.document.value.decision is PlanPolicyDecision.ALLOW
    assert deny.record.document.value.decision is PlanPolicyDecision.DENY
    assert allow.record.document.value.policy_sha256 != deny.record.document.value.policy_sha256
    assert allow.record.decision_ref != deny.record.decision_ref
    with database.unit_of_work() as work:
        assert len(work.plan_decisions.list_for_plan(plan.execution_plan_id)) == 3
        assert all(
            item.document.kind != "APPROVAL"
            for item in work.plan_decisions.list_for_plan(plan.execution_plan_id)
        )
