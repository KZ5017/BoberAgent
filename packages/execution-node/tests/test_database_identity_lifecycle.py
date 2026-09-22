"""Node-local database, identity, configuration, and lifecycle tests."""

from pathlib import Path

import pytest
from boberagent_execution_node import NodeConfiguration, NodeId
from boberagent_execution_node.identity import load_or_create_identity
from boberagent_execution_node.lifecycle import NodeLifecycle, NodeLifecycleState
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import (
    current_revision,
    upgrade_database,
)
from pydantic import ValidationError
from sqlalchemy import inspect, text


def test_empty_database_migrates_and_survives_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    database = RuntimeDatabase(database_path)
    assert current_revision(database) is None

    upgrade_database(database)
    assert current_revision(database) == "0005_durable_interactions"
    assert set(inspect(database.migration_engine).get_table_names()) == {
        "alembic_version",
        "artifact_spool",
        "event_outbox",
        "managed_processes",
        "result_outbox",
        "runtime_interactions",
        "runtime_resources",
        "runtime_runs",
        "runtime_sessions",
        "workspaces",
    }
    database.close()

    reopened = RuntimeDatabase(database_path)
    try:
        assert current_revision(reopened) == "0005_durable_interactions"
        upgrade_database(reopened)
    finally:
        reopened.close()


def test_invocation_fingerprint_migration_upgrades_milestone_4_schema(
    tmp_path: Path,
) -> None:
    database = RuntimeDatabase(tmp_path / "upgrade.sqlite3")
    try:
        upgrade_database(database, "0001_runtime_foundation")
        assert current_revision(database) == "0001_runtime_foundation"
        columns = {
            column["name"]
            for column in inspect(database.migration_engine).get_columns("runtime_runs")
        }
        assert "invocation_fingerprint" not in columns

        upgrade_database(database)
        assert current_revision(database) == "0005_durable_interactions"
        columns = {
            column["name"]
            for column in inspect(database.migration_engine).get_columns("runtime_runs")
        }
        assert "invocation_fingerprint" in columns
    finally:
        database.close()


def test_artifact_sync_migration_preserves_milestone_5_spool_metadata(
    tmp_path: Path,
) -> None:
    database = RuntimeDatabase(tmp_path / "artifact-upgrade.sqlite3")
    try:
        upgrade_database(database, "0002_invocation_fingerprint")
        with database.migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime_runs "
                    "(run_id, mission_id, capability_id, operation, status, created_at) VALUES "
                    "('run-upgrade', 'mission-upgrade', 'test.upgrade', 'run', 'COMPLETED', "
                    "'2026-01-01T00:00:00+00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO artifact_spool "
                    "(artifact_id, artifact_type, storage_ref, run_id, created_at, sha256, "
                    "size_bytes, metadata_json, local_path, sync_state) VALUES "
                    "('artifact-upgrade', 'test.raw', 'node-spool:old', 'run-upgrade', "
                    "'2026-01-01T00:00:00+00:00', :digest, 7, '{}', '/managed/blob', "
                    "'LOCAL_ONLY')"
                ),
                {"digest": "b" * 64},
            )

        upgrade_database(database)
        assert current_revision(database) == "0005_durable_interactions"
        with database.migration_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT artifact_id, sync_state, sync_attempt_count FROM artifact_spool "
                    "WHERE artifact_id = 'artifact-upgrade'"
                )
            ).one()
        assert tuple(row) == ("artifact-upgrade", "LOCAL_ONLY", 0)
    finally:
        database.close()


def test_resource_session_migration_upgrades_previous_node_schema(tmp_path: Path) -> None:
    database = RuntimeDatabase(tmp_path / "resource-session-upgrade.sqlite3")
    try:
        upgrade_database(database, "0003_artifact_sync_metadata")
        assert current_revision(database) == "0003_artifact_sync_metadata"
        assert "runtime_resources" not in inspect(database.migration_engine).get_table_names()
        with database.migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO runtime_runs "
                    "(run_id, mission_id, capability_id, operation, status, created_at) VALUES "
                    "('run-before-browser', 'mission-upgrade', 'test.existing', 'run', "
                    "'COMPLETED', '2026-01-01T00:00:00+00:00')"
                )
            )

        upgrade_database(database)
        assert current_revision(database) == "0005_durable_interactions"
        tables = set(inspect(database.migration_engine).get_table_names())
        assert {"runtime_interactions", "runtime_resources", "runtime_sessions"} <= tables
        with database.migration_engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT run_id FROM runtime_runs WHERE run_id = 'run-before-browser'")
                ).scalar_one()
                == "run-before-browser"
            )
    finally:
        database.close()


def test_node_identity_is_generated_once_and_configurable(tmp_path: Path) -> None:
    identity_path = tmp_path / "identity.json"
    generated = load_or_create_identity(identity_path)
    restored = load_or_create_identity(identity_path)

    assert generated == restored
    assert generated.node_id.startswith("node-")

    explicit_path = tmp_path / "explicit.json"
    configured = load_or_create_identity(explicit_path, NodeId("node-lab-01"))
    assert configured.node_id == NodeId("node-lab-01")
    with pytest.raises(ValueError, match="does not match"):
        load_or_create_identity(explicit_path, NodeId("node-lab-02"))


def test_configuration_derives_owned_runtime_paths(tmp_path: Path) -> None:
    configuration = NodeConfiguration.for_runtime_directory(
        tmp_path / "runtime", configured_node_id="node-configured"
    )
    configuration.prepare_directories()

    assert configuration.database_path.parent == configuration.runtime_directory
    assert configuration.process_output_root.is_dir()
    assert configuration.workspace_root.is_dir()
    assert configuration.artifact_spool_root.is_dir()
    with pytest.raises(ValidationError):
        NodeConfiguration.for_runtime_directory(tmp_path / "bad", configured_node_id="bad id")


def test_lifecycle_allows_only_explicit_transitions() -> None:
    lifecycle = NodeLifecycle()
    lifecycle.transition(NodeLifecycleState.STARTING)
    lifecycle.transition(NodeLifecycleState.READY)
    lifecycle.transition(NodeLifecycleState.DRAINING)
    lifecycle.transition(NodeLifecycleState.OFFLINE)

    with pytest.raises(ValueError, match="invalid Node lifecycle transition"):
        lifecycle.transition(NodeLifecycleState.READY)
