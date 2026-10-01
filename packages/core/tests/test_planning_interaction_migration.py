"""D6 owner migration preserves existing Run interactions and fresh installation."""

from datetime import UTC, datetime
from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from sqlalchemy import inspect, text


def test_upgrade_preserves_m15_run_interaction(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0014_m20_d5_policy_identity")
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO interactions (interaction_id,node_id,run_id,mission_id,state,"
                    "request_json,requested_at) VALUES (:id,:node,:run,:mission,:state,:request,:at)"
                ),
                {
                    "id": "interaction-legacy",
                    "node": "node-legacy",
                    "run": "run-legacy",
                    "mission": "mission-legacy",
                    "state": "REQUESTED",
                    "request": '{"legacy":true}',
                    "at": datetime(2026, 9, 29, tzinfo=UTC).isoformat(),
                },
            )
        upgrade_database(database)
        assert current_revision(database) == "0017_m20_e3_import_progress"
        with database._migration_engine.connect() as connection:
            row = connection.execute(
                text("SELECT owner_kind,node_id,run_id,planning_attempt_id FROM interactions")
            ).one()
        assert tuple(row) == ("CAPABILITY_RUN", "node-legacy", "run-legacy", None)
    finally:
        database.dispose()


def test_fresh_migration_has_planning_owner_columns(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database)
        assert current_revision(database) == "0017_m20_e3_import_progress"
        columns = {
            item["name"] for item in inspect(database._migration_engine).get_columns("interactions")
        }
        assert {"owner_kind", "planning_attempt_id", "purpose", "proposal_revision"} <= columns
    finally:
        database.dispose()
