"""Independent callers reuse one immutable policy assessment through DB uniqueness."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from boberagent_core import CoreDatabase
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from test_core_poc_acquisition import NOW
from test_planning_policy import _plan, _profile


def test_concurrent_identical_assessment_has_one_policy_row(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, _ = _plan(database, tmp_path)
    service = CorePlanPolicyService(
        database, PolicyProfileRegistry((_profile(plan),)), clock=lambda: NOW
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(service.evaluate, (plan.execution_plan_id,) * 2))
    assert results[0].record.decision_ref == results[1].record.decision_ref
    with database.unit_of_work() as work:
        assert len(work.plan_decisions.list_for_plan(plan.execution_plan_id)) == 2
