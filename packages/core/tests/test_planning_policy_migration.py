"""D5 forward migration preserves D2 history and constrains policy context identity."""

from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from planning_persistence_fixtures import attempt_fixture, seed
from sqlalchemy import inspect


def test_upgrade_from_d2_preserves_planning_attempt(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0013_m20_d2_planning")
        assert current_revision(database) == "0013_m20_d2_planning"
        seed(database)
        attempt = attempt_fixture()
        with database.unit_of_work() as work:
            work.planning_attempts.add(attempt)
        upgrade_database(database)
        assert current_revision(database) == "0014_m20_d5_policy_identity"
        with database.unit_of_work() as work:
            assert work.planning_attempts.get(attempt.planning_attempt_ref) == attempt
        indexes = inspect(database._migration_engine).get_indexes("plan_decisions")
        assert any(item["name"] == "uq_plan_policy_context" and item["unique"] for item in indexes)
    finally:
        database.dispose()
