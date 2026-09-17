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
    "result_ingestions",
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
        assert current_revision(database) == "0005_result_ingestion"
    finally:
        database.dispose()


def test_migrated_database_can_be_reopened(database_path: Path) -> None:
    first = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(first)
    first.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(reopened)
        assert current_revision(reopened) == "0005_result_ingestion"
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
        assert current_revision(database) == "0005_result_ingestion"
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
        assert current_revision(database) == "0005_result_ingestion"
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
        assert current_revision(database) == "0005_result_ingestion"
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


def test_result_ingestion_migration_upgrades_milestone_8_without_data_loss(
    database_path: Path,
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0004_capability_registry")
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO missions "
                    "(mission_id, status, created_at, metadata_json) VALUES "
                    "('mission-m9-upgrade', 'ACTIVE', '2026-01-01T00:00:00+00:00', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO capability_runs "
                    "(run_id, mission_id, capability_id, operation, status, created_at) VALUES "
                    "('run-m9-upgrade', 'mission-m9-upgrade', 'test.capability', 'run', "
                    "'CREATED', '2026-01-01T00:00:00+00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO assets "
                    "(asset_id, mission_id, kind, primary_address, created_at, metadata_json) "
                    "VALUES ('asset-m9-upgrade', 'mission-m9-upgrade', 'host', '192.0.2.9', "
                    "'2026-01-01T00:00:00+00:00', '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO artifacts "
                    "(artifact_id, artifact_type, storage_ref, run_id, created_at, metadata_json, "
                    "content_state, received_bytes) VALUES "
                    "('artifact-m9-upgrade', 'test.raw', 'storage:test', 'run-m9-upgrade', "
                    "'2026-01-01T00:00:00+00:00', '{}', 'METADATA_ONLY', 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO observations "
                    "(observation_id, observation_type, subject_ref, value_json, confidence, "
                    "observed_at, run_id, evidence_refs_json, materialization_status) VALUES "
                    "('observation-m9-upgrade', 'network.service', 'asset-m9-upgrade', "
                    "'{}', 1.0, "
                    "'2026-01-01T00:00:00+00:00', 'run-m9-upgrade', '[]', 'MATERIALIZED')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO services "
                    "(service_id, asset_id, transport, port, state, first_observed_at, "
                    "last_observed_at, current_observation_id, provenance_refs_json) VALUES "
                    "('service-m9-upgrade', 'asset-m9-upgrade', 'tcp', 22, 'open', "
                    "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
                    "'observation-m9-upgrade', '[\"observation-m9-upgrade\"]')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO capability_providers "
                    "(provider_id, node_id, capability_id, definition_json, "
                    "implementation_version, reported_status, availability, "
                    "first_registered_at, last_seen_at, node_lifecycle, node_database_ready, "
                    "node_degraded_reasons_json) VALUES "
                    "('00000000-0000-0000-0000-000000000009', 'node-m9-upgrade', "
                    "'test.capability', '{}', '1.0.0', 'AVAILABLE', 'AVAILABLE', "
                    "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
                    "'READY', 1, '[]')"
                )
            )
        upgrade_database(database)
        assert current_revision(database) == "0005_result_ingestion"
        assert "result_ingestions" in inspect(database._migration_engine).get_table_names()
        with database._migration_engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM capability_runs WHERE run_id = 'run-m9-upgrade'")
                ).scalar_one()
                == "CREATED"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT content_state FROM artifacts WHERE artifact_id = 'artifact-m9-upgrade'"
                    )
                ).scalar_one()
                == "METADATA_ONLY"
            )
            assert connection.execute(text("SELECT count(*) FROM observations")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM services")).scalar_one() == 1
            assert (
                connection.execute(text("SELECT count(*) FROM capability_providers")).scalar_one()
                == 1
            )
    finally:
        database.dispose()


def test_database_configuration_rejects_non_sqlite() -> None:
    try:
        DatabaseConfig("postgresql://example.invalid/core")
    except ValueError as error:
        assert "SQLite only" in str(error)
    else:
        raise AssertionError("non-SQLite URL was accepted")
