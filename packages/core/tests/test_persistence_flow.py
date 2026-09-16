"""Milestone 2 integration flow across a real database reopen."""

from pathlib import Path

from boberagent_contracts import AssetRef, Observation, ObservationRef
from boberagent_core import (
    Asset,
    CoreDatabase,
    CorePersistence,
    DatabaseConfig,
    MaterializationStatus,
    upgrade_database,
)
from conftest import NOW, add_artifact, add_mission_and_run


def test_service_materialization_survives_database_reopen(database_path: Path) -> None:
    config = DatabaseConfig.sqlite(database_path)
    database = CoreDatabase(config)
    upgrade_database(database)
    run = add_mission_and_run(database)
    artifact = add_artifact(database, run)
    asset = Asset(
        asset_ref=AssetRef("asset-reopen"),
        mission_ref=run.mission_ref,
        kind="host",
        primary_address="198.51.100.7",
        created_at=NOW,
    )
    item = Observation.model_validate(
        {
            "observation_id": "observation-reopen",
            "type": "network.service",
            "subject_ref": str(asset.asset_ref),
            "value": {
                "transport": "tcp",
                "port": 8080,
                "state": "open",
                "service": "http-proxy",
            },
            "run_ref": str(run.run_id),
            "observed_at": NOW,
            "evidence_refs": [str(artifact.artifact_id)],
        }
    )
    core = CorePersistence(database)
    core.create_asset(asset)
    core.append_observation(item)
    assert core.materialize_observation(item.observation_id) is MaterializationStatus.MATERIALIZED
    assert len(core.services_for_asset(asset.asset_ref)) == 1
    database.dispose()

    reopened_database = CoreDatabase(config)
    reopened = CorePersistence(reopened_database)
    try:
        service = reopened.services_for_asset(asset.asset_ref)[0]
        stored = reopened.get_observation(ObservationRef("observation-reopen"))
        assert (service.transport, service.port, service.service) == ("tcp", 8080, "http-proxy")
        assert stored is not None
        assert stored.materialization_status is MaterializationStatus.MATERIALIZED
        assert stored.observation.value == item.value
    finally:
        reopened_database.dispose()
