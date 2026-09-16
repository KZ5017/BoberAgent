"""Append-only Observation storage and deterministic Service reduction."""

from datetime import timedelta

import pytest
from boberagent_contracts import ArtifactRef, AssetRef, Observation
from boberagent_core import (
    Asset,
    CoreDatabase,
    MaterializationStatus,
    ReducerRegistry,
    service_ref_for_endpoint,
)
from conftest import NOW, add_artifact, add_mission_and_run
from pydantic import ValidationError


def setup_subject(database: CoreDatabase) -> tuple[Asset, ArtifactRef]:
    run = add_mission_and_run(database)
    artifact = add_artifact(database, run)
    asset = Asset(
        asset_ref=AssetRef("asset-service"),
        mission_ref=run.mission_ref,
        kind="host",
        primary_address="192.0.2.20",
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.assets.add(asset)
    return asset, artifact.artifact_id


def observation(
    observation_ref: str,
    asset: Asset,
    evidence_ref: ArtifactRef,
    *,
    value: object,
    observed_offset: int = 0,
    observation_type: str = "network.service",
) -> Observation:
    return Observation.model_validate(
        {
            "observation_id": observation_ref,
            "type": observation_type,
            "subject_ref": str(asset.asset_ref),
            "value": value,
            "run_ref": "run-test",
            "observed_at": NOW + timedelta(seconds=observed_offset),
            "confidence": 0.9,
            "evidence_refs": [str(evidence_ref)],
        }
    )


def test_observation_round_trip_preserves_json_and_evidence(database: CoreDatabase) -> None:
    asset, evidence_ref = setup_subject(database)
    item = observation(
        "observation-json",
        asset,
        evidence_ref,
        value={"nested": [1, True, None, {"label": "https"}]},
        observation_type="custom.evidence",
    )
    with database.unit_of_work() as work:
        work.observations.append(item)

    with database.unit_of_work() as work:
        stored = work.observations.get(item.observation_id)
        assert stored is not None
        assert stored.observation == item
        assert stored.materialization_status is MaterializationStatus.PENDING
        assert not hasattr(work.observations, "update")

    with pytest.raises(ValidationError):
        stored.observation.value = {"changed": True}


def test_valid_service_materializes_and_replay_is_idempotent(database: CoreDatabase) -> None:
    asset, evidence_ref = setup_subject(database)
    item = observation(
        "observation-service",
        asset,
        evidence_ref,
        value={
            "transport": "TCP",
            "port": 443,
            "state": "OPEN",
            "service": "HTTPS",
            "product": "Example Server",
            "version": "1.0",
        },
    )
    registry = ReducerRegistry()
    with database.unit_of_work() as work:
        work.observations.append(item)
        assert registry.materialize(item.observation_id, work) is MaterializationStatus.MATERIALIZED
        assert registry.materialize(item.observation_id, work) is MaterializationStatus.MATERIALIZED

    with database.unit_of_work() as work:
        services = work.services.list_for_asset(asset.asset_ref)
        assert len(services) == 1
        service = services[0]
        assert service.service_ref == service_ref_for_endpoint(asset.asset_ref, "tcp", 443)
        assert (service.transport, service.port, service.state) == ("tcp", 443, "open")
        assert service.provenance_refs == (item.observation_id,)


def test_later_observation_updates_endpoint_without_duplicate(database: CoreDatabase) -> None:
    asset, evidence_ref = setup_subject(database)
    initial = observation(
        "observation-earlier",
        asset,
        evidence_ref,
        value={"transport": "tcp", "port": 22, "state": "open", "service": "ssh"},
    )
    later = observation(
        "observation-later",
        asset,
        evidence_ref,
        observed_offset=10,
        value={"transport": "tcp", "port": 22, "state": "filtered"},
    )
    registry = ReducerRegistry()
    with database.unit_of_work() as work:
        work.observations.append(initial)
        registry.materialize(initial.observation_id, work)
        work.observations.append(later)
        registry.materialize(later.observation_id, work)

    with database.unit_of_work() as work:
        services = work.services.list_for_asset(asset.asset_ref)
        assert len(services) == 1
        service = services[0]
        assert service.state == "filtered"
        assert service.service is None
        assert service.current_observation_ref == later.observation_id
        assert service.provenance_refs == (initial.observation_id, later.observation_id)
        assert work.observations.get(initial.observation_id) is not None
        assert work.observations.get(later.observation_id) is not None


def test_older_conflict_preserves_current_fields_but_adds_provenance(
    database: CoreDatabase,
) -> None:
    asset, evidence_ref = setup_subject(database)
    current = observation(
        "observation-current",
        asset,
        evidence_ref,
        observed_offset=20,
        value={"transport": "udp", "port": 53, "state": "open", "service": "domain"},
    )
    older = observation(
        "observation-older",
        asset,
        evidence_ref,
        observed_offset=5,
        value={"transport": "udp", "port": 53, "state": "closed"},
    )
    registry = ReducerRegistry()
    with database.unit_of_work() as work:
        work.observations.append(current)
        registry.materialize(current.observation_id, work)
        work.observations.append(older)
        registry.materialize(older.observation_id, work)

    with database.unit_of_work() as work:
        service = work.services.list_for_asset(asset.asset_ref)[0]
        assert service.state == "open"
        assert service.current_observation_ref == current.observation_id
        assert set(service.provenance_refs) == {current.observation_id, older.observation_id}


def test_malformed_and_unknown_observations_are_quarantined(database: CoreDatabase) -> None:
    asset, evidence_ref = setup_subject(database)
    malformed = observation(
        "observation-malformed",
        asset,
        evidence_ref,
        value={"transport": "tcp", "port": 70000, "state": "open"},
    )
    unknown = observation(
        "observation-unknown",
        asset,
        evidence_ref,
        value={"value": 1},
        observation_type="future.observation",
    )
    registry = ReducerRegistry()
    with database.unit_of_work() as work:
        work.observations.append(malformed)
        work.observations.append(unknown)
        assert (
            registry.materialize(malformed.observation_id, work) is MaterializationStatus.REJECTED
        )
        assert (
            registry.materialize(unknown.observation_id, work) is MaterializationStatus.UNSUPPORTED
        )

    with database.unit_of_work() as work:
        assert work.services.list_for_asset(asset.asset_ref) == ()
        rejected = work.observations.get(malformed.observation_id)
        unsupported = work.observations.get(unknown.observation_id)
        assert rejected is not None and rejected.materialization_error
        assert unsupported is not None
        assert unsupported.materialization_status is MaterializationStatus.UNSUPPORTED
