"""Migration behavior from an empty SQLite database."""

from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, current_revision, upgrade_database
from sqlalchemy import inspect

EXPECTED_TABLES = {
    "alembic_version",
    "artifacts",
    "assets",
    "capability_runs",
    "goals",
    "missions",
    "observations",
    "services",
    "workflow_runs",
}


def test_migration_upgrades_empty_database(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        assert not database_path.exists()
        upgrade_database(database)
        assert set(inspect(database._migration_engine).get_table_names()) == EXPECTED_TABLES
        assert current_revision(database) == "0001_core_persistence"
    finally:
        database.dispose()


def test_migrated_database_can_be_reopened(database_path: Path) -> None:
    first = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(first)
    first.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(reopened)
        assert current_revision(reopened) == "0001_core_persistence"
    finally:
        reopened.dispose()


def test_database_configuration_rejects_non_sqlite() -> None:
    try:
        DatabaseConfig("postgresql://example.invalid/core")
    except ValueError as error:
        assert "SQLite only" in str(error)
    else:
        raise AssertionError("non-SQLite URL was accepted")
