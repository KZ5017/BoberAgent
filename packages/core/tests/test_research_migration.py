"""Forward migration from M16 metadata preserves existing Core-owned records."""

from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from sqlalchemy import inspect, text


def test_m20_research_migration_preserves_existing_state(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0008_secret_credentials")
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO missions (mission_id, status, created_at, metadata_json) "
                    "VALUES ('mission-before-m20', 'ACTIVE', '2026-01-01T00:00:00+00:00', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO assets (asset_id, mission_id, kind, primary_address, "
                    "created_at, metadata_json) VALUES ('asset-before-m20', "
                    "'mission-before-m20', 'host', '192.0.2.30', "
                    "'2026-01-01T00:00:00+00:00', '{}')"
                )
            )
        upgrade_database(database)
        assert current_revision(database) == "0009_m20_research"
        tables = set(inspect(database._migration_engine).get_table_names())
        assert {
            "vulnerability_hypotheses",
            "research_attempts",
            "poc_candidates",
            "research_source_hits",
        } <= tables
        with database._migration_engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM missions")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM assets")).scalar_one() == 1
    finally:
        database.dispose()
