"""D5 migration must not erase valid D2 multi-decision policy history."""

from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from boberagent_core.planning.models import PlanPolicyAssessment
from boberagent_core.planning.records import PlanDecisionRecord, PlanDecisionRef, PolicyDocument
from planning_persistence_fixtures import attempt_fixture, finalize, seed
from test_planning_plan_history import decisions


def test_upgrade_keeps_old_same_context_policy_variants(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0013_m20_d2_planning")
        seed(database)
        finalize(database, attempt_fixture())
        original = decisions()[1]
        denied = PlanDecisionRecord(
            decision_ref=PlanDecisionRef("policy-legacy-denied"),
            document=PolicyDocument(
                value=PlanPolicyAssessment.model_validate(
                    {**original.document.value.model_dump(), "decision": "DENY"}
                )
            ),
            context=original.context,
            created_at=original.created_at,
        )
        with database.unit_of_work() as work:
            work.plan_decisions.append(original)
            work.plan_decisions.append(denied)
        upgrade_database(database)
        assert current_revision(database) == "0015_m20_d6_planning_interactions"
        with database.unit_of_work() as work:
            assert work.plan_decisions.get(original.decision_ref) == original
            assert work.plan_decisions.get(denied.decision_ref) == denied
    finally:
        database.dispose()
