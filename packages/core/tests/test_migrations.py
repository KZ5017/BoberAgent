"""Migration behavior from an empty SQLite database."""

from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from sqlalchemy import inspect, text

EXPECTED_TABLES = {
    "alembic_version",
    "artifacts",
    "assets",
    "capability_runs",
    "capability_providers",
    "capability_routing_decisions",
    "goals",
    "missions",
    "observations",
    "services",
    "transport_inbox",
    "workflow_runs",
}


def test_migration_upgrades_empty_database(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        assert not database_path.exists()
        upgrade_database(database)
        assert set(inspect(database._migration_engine).get_table_names()) == EXPECTED_TABLES
        assert current_revision(database) == "0004_capability_registry"
    finally:
        database.dispose()


def test_migrated_database_can_be_reopened(database_path: Path) -> None:
    first = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(first)
    first.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(reopened)
        assert current_revision(reopened) == "0004_capability_registry"
    finally:
        reopened.dispose()


def test_transport_inbox_migration_upgrades_milestone_2_schema(
    database_path: Path,
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0001_core_persistence")
        assert current_revision(database) == "0001_core_persistence"
        assert "transport_inbox" not in inspect(database._migration_engine).get_table_names()

        upgrade_database(database)
        assert current_revision(database) == "0004_capability_registry"
        assert "transport_inbox" in inspect(database._migration_engine).get_table_names()
    finally:
        database.dispose()


def test_capability_registry_migration_upgrades_milestone_7_schema(
    database_path: Path,
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0003_artifact_content")
        assert current_revision(database) == "0003_artifact_content"
        tables = set(inspect(database._migration_engine).get_table_names())
        assert "capability_providers" not in tables

        upgrade_database(database)
        assert current_revision(database) == "0004_capability_registry"
        tables = set(inspect(database._migration_engine).get_table_names())
        assert {"capability_providers", "capability_routing_decisions"} <= tables
    finally:
        database.dispose()


def test_artifact_content_migration_preserves_milestone_5_metadata(
    database_path: Path,
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0002_transport_inbox")
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO missions "
                    "(mission_id, status, created_at, metadata_json) "
                    "VALUES ('mission-upgrade', 'ACTIVE', '2026-01-01T00:00:00+00:00', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO capability_runs "
                    "(run_id, mission_id, capability_id, operation, status, created_at) "
                    "VALUES ('run-upgrade', 'mission-upgrade', 'test.upgrade', 'run', "
                    "'COMPLETED', '2026-01-01T00:00:00+00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO artifacts "
                    "(artifact_id, artifact_type, storage_ref, run_id, created_at, sha256, "
                    "size_bytes, metadata_json) VALUES "
                    "('artifact-upgrade', 'test.raw', 'storage:old', 'run-upgrade', "
                    "'2026-01-01T00:00:00+00:00', :digest, 7, '{}')"
                ),
                {"digest": "a" * 64},
            )

        upgrade_database(database)
        assert current_revision(database) == "0004_capability_registry"
        columns = {
            str(column["name"])
            for column in inspect(database._migration_engine).get_columns("artifacts")
        }
        assert {"content_state", "content_key", "received_bytes"} <= columns
        with database._migration_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT artifact_id, content_state, received_bytes FROM artifacts "
                    "WHERE artifact_id = 'artifact-upgrade'"
                )
            ).one()
        assert tuple(row) == ("artifact-upgrade", "METADATA_ONLY", 0)
    finally:
        database.dispose()


def test_database_configuration_rejects_non_sqlite() -> None:
    try:
        DatabaseConfig("postgresql://example.invalid/core")
    except ValueError as error:
        assert "SQLite only" in str(error)
    else:
        raise AssertionError("non-SQLite URL was accepted")
