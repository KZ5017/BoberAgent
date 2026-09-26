"""Fresh and forward M20-B1 migrations preserve M20-A history."""

from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from sqlalchemy import inspect, text


def test_acquisition_migration_from_research_preserves_history(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0009_m20_research")
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO missions (mission_id, status, created_at, metadata_json) "
                    "VALUES ('mission-pre-b1', 'ACTIVE', '2026-01-01T00:00:00+00:00', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO assets (asset_id, mission_id, kind, primary_address, "
                    "created_at, metadata_json) VALUES ('asset-pre-b1', 'mission-pre-b1', "
                    "'host', '192.0.2.30', '2026-01-01T00:00:00+00:00', '{}')"
                )
            )
        assert current_revision(database) == "0009_m20_research"
        upgrade_database(database)
        assert current_revision(database) == "0010_m20_acquisition"
        assert "poc_acquisitions" in inspect(database._migration_engine).get_table_names()
        columns = {
            column["name"]
            for column in inspect(database._migration_engine).get_columns("poc_acquisitions")
        }
        assert {
            "acquisition_id",
            "selected_hit_id",
            "research_attempt_id",
            "run_id",
            "resolved_commit_sha",
            "raw_artifact_id",
            "manifest_artifact_id",
            "receipt_json",
        } <= columns
        with database._migration_engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM missions")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM assets")).scalar_one() == 1
    finally:
        database.dispose()


def test_fresh_migration_and_reopen(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database)
        assert current_revision(database) == "0010_m20_acquisition"
    finally:
        database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        assert current_revision(reopened) == "0010_m20_acquisition"
        assert "poc_acquisitions" in inspect(reopened._migration_engine).get_table_names()
    finally:
        reopened.dispose()
