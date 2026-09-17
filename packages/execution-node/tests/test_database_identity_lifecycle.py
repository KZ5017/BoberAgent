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
from sqlalchemy import inspect


def test_empty_database_migrates_and_survives_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    database = RuntimeDatabase(database_path)
    assert current_revision(database) is None

    upgrade_database(database)
    assert current_revision(database) == "0002_invocation_fingerprint"
    assert set(inspect(database.migration_engine).get_table_names()) == {
        "alembic_version",
        "artifact_spool",
        "event_outbox",
        "managed_processes",
        "result_outbox",
        "runtime_runs",
        "workspaces",
    }
    database.close()

    reopened = RuntimeDatabase(database_path)
    try:
        assert current_revision(reopened) == "0002_invocation_fingerprint"
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
        assert current_revision(database) == "0002_invocation_fingerprint"
        columns = {
            column["name"]
            for column in inspect(database.migration_engine).get_columns("runtime_runs")
        }
        assert "invocation_fingerprint" in columns
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
