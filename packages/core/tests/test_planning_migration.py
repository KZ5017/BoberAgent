"""Fresh/previous-head migrations preserve prior data and enforce D2 history constraints."""

from pathlib import Path

import pytest
from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from boberagent_core.persistence.planning_orm import PlanningAttemptRow
from boberagent_core.planning import PlanningAttemptLifecycle as State
from plan_test_fixtures import NOW
from planning_persistence_fixtures import attempt_fixture, seed
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import IntegrityError


def test_fresh_head_and_upgrade_preserve_previous_metadata(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0012_m20_c1_inspection")
        seed(database)
        with database._migration_engine.connect() as connection:
            before = tuple(
                connection.execute(
                    text(
                        "SELECT inspection_id, document_json FROM poc_inspections ORDER BY inspection_id"
                    )
                )
            )
        assert "planning_attempts" not in inspect(database._migration_engine).get_table_names()
        upgrade_database(database)
        assert current_revision(database) == "0017_m20_e3_import_progress"
        tables = set(inspect(database._migration_engine).get_table_names())
        assert {"planning_attempts", "execution_plans", "plan_decisions"} <= tables
        with database._migration_engine.connect() as connection:
            after = tuple(
                connection.execute(
                    text(
                        "SELECT inspection_id, document_json FROM poc_inspections ORDER BY inspection_id"
                    )
                )
            )
            assert after == before
            assert connection.execute(text("SELECT count(*) FROM artifacts")).scalar_one() == 2
        indexes = inspect(database._migration_engine).get_indexes("planning_attempts")
        assert any(
            index["name"] == "uq_planning_attempt_reusable_request" and index["unique"]
            for index in indexes
        )
        constraints = inspect(database._migration_engine).get_check_constraints("planning_attempts")
        assert {"ck_planning_lifecycle", "ck_planning_revision", "ck_planning_completion_time"} <= {
            constraint["name"] for constraint in constraints
        }
    finally:
        database.dispose()


def test_database_unique_constraint_and_immutable_terminal_history(database: CoreDatabase) -> None:
    seed(database)
    attempt = attempt_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
    with database._migration_engine.connect() as connection:
        mapping = dict(connection.execute(text("SELECT * FROM planning_attempts")).mappings().one())
    # Use the private mapped table only to prove database-level constraints, bypassing repositories.
    mapping["request_json"] = attempt.request.model_dump(mode="json")
    mapping["history_json"] = {"schema_version": "plan-proposal-history-v1", "revisions": []}
    mapping["diagnostic_codes_json"] = []
    mapping["created_at"] = NOW
    mapping["updated_at"] = NOW
    mapping["attempt_id"] = "planning-illegal-duplicate"
    with (
        database._migration_engine.begin() as connection,
        pytest.raises(IntegrityError, match="UNIQUE"),
    ):
        connection.execute(insert(PlanningAttemptRow).values(**mapping))
    with (
        database._migration_engine.begin() as connection,
        pytest.raises(IntegrityError, match="CHECK"),
    ):
        connection.execute(text("UPDATE planning_attempts SET revision_number = -1"))
    with database.unit_of_work() as work:
        work.planning_attempts.update_lifecycle(
            attempt.planning_attempt_ref,
            State.CANCELLED,
            expected_state=State.REQUESTED,
            expected_revision=0,
            updated_at=NOW,
        )
    with (
        database._migration_engine.begin() as connection,
        pytest.raises(IntegrityError, match="immutable terminal"),
    ):
        connection.execute(
            text("UPDATE planning_attempts SET lifecycle = 'REQUESTED', completed_at = NULL")
        )
    with (
        database._migration_engine.begin() as connection,
        pytest.raises(IntegrityError, match="immutable"),
    ):
        connection.execute(text("DELETE FROM planning_attempts"))


def test_foreign_key_and_identity_constraints(database: CoreDatabase) -> None:
    seed(database)
    attempt = attempt_fixture()
    with database.unit_of_work() as work:
        work.planning_attempts.add(attempt)
    with (
        database._migration_engine.begin() as connection,
        pytest.raises(IntegrityError, match="immutable planning request"),
    ):
        connection.execute(
            text("UPDATE planning_attempts SET request_fingerprint = :value"), {"value": "c" * 64}
        )
    assert len(inspect(database._migration_engine).get_foreign_keys("planning_attempts")) == 6
    assert len(inspect(database._migration_engine).get_foreign_keys("execution_plans")) == 3
