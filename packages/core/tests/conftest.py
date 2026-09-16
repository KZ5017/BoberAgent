"""Fixtures for isolated migration-backed Core persistence tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    StorageRef,
)
from boberagent_core import CoreDatabase, DatabaseConfig, Mission, upgrade_database

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "core.sqlite3"


@pytest.fixture
def database(database_path: Path) -> Iterator[CoreDatabase]:
    core_database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(core_database)
    try:
        yield core_database
    finally:
        core_database.dispose()


def add_mission_and_run(database: CoreDatabase) -> CapabilityRun:
    mission = Mission(
        mission_ref=MissionRef("mission-test"),
        status="ACTIVE",
        created_at=NOW,
        name="Test mission",
    )
    run = CapabilityRun(
        run_id=CapabilityRunRef("run-test"),
        capability_id="network.service_discovery",
        operation="discover",
        mission_ref=mission.mission_ref,
        status=CapabilityRunStatus.COMPLETED,
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW,
    )
    with database.unit_of_work() as work:
        work.missions.add(mission)
        work.runs.add(run)
    return run


def add_artifact(database: CoreDatabase, run: CapabilityRun) -> ArtifactDescriptor:
    artifact = ArtifactDescriptor(
        artifact_id=ArtifactRef("artifact-test"),
        artifact_type="network.scan.raw",
        storage_ref=StorageRef("storage:artifact-test"),
        created_by_run=run.run_id,
        created_at=NOW,
        sha256="a" * 64,
        size_bytes=42,
        media_type="application/json",
        metadata={"source": "fixture"},
    )
    with database.unit_of_work() as work:
        work.artifacts.add(artifact)
    return artifact
