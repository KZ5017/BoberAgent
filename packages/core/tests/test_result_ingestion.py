"""Durable, idempotent CapabilityResult ingestion into materialized World State."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    AssetRef,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    Diagnostic,
    DiagnosticSeverity,
    MissionRef,
    Observation,
    StorageRef,
)
from boberagent_core import (
    ArtifactContentState,
    Asset,
    CapabilityRegistry,
    ConflictingResultError,
    CoreDatabase,
    CoreTransportReceiver,
    DatabaseConfig,
    Mission,
    ResultIngestionService,
    ResultIngestionStatus,
    RoutingDecision,
    upgrade_database,
)
from boberagent_transport import ResultEnvelope, result_message_id, serialize_message
from conftest import NOW
from test_capability_registry import advertisement, capability_definition

MISSION = MissionRef("mission-ingestion")
ASSET = AssetRef("asset-ingestion")


def _setup_run(database: CoreDatabase, run_id: str = "run-ingestion") -> CapabilityRun:
    mission = Mission(mission_ref=MISSION, status="ACTIVE", created_at=NOW)
    asset = Asset(
        asset_ref=ASSET,
        mission_ref=MISSION,
        kind="host",
        primary_address="192.0.2.10",
        created_at=NOW,
    )
    run = CapabilityRun(
        run_id=CapabilityRunRef(run_id),
        capability_id="network.service_discovery",
        operation="discover",
        mission_ref=MISSION,
        status=CapabilityRunStatus.CREATED,
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.missions.add(mission)
        work.assets.add(asset)
        work.runs.add(run)
    return run


def _artifact(run_ref: CapabilityRunRef, suffix: str = "raw") -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=ArtifactRef(f"artifact-{suffix}"),
        artifact_type="network_scan.raw_xml",
        storage_ref=StorageRef(f"node-spool:{suffix}"),
        created_by_run=run_ref,
        created_at=NOW,
        sha256="a" * 64,
        size_bytes=42,
        media_type="application/xml",
        metadata={"profile": "quick"},
    )


def _observation(
    run_ref: CapabilityRunRef,
    observation_id: str,
    *,
    port: int = 22,
    observation_type: str = "network.service",
    value: object | None = None,
    observed_offset: int = 0,
) -> Observation:
    return Observation.model_validate(
        {
            "observation_id": observation_id,
            "type": observation_type,
            "subject_ref": str(ASSET),
            "value": value
            if value is not None
            else {
                "transport": "tcp",
                "port": port,
                "state": "open",
                "service": "ssh" if port == 22 else "http",
            },
            "run_ref": str(run_ref),
            "observed_at": NOW + timedelta(seconds=observed_offset),
            "confidence": 1.0,
            "evidence_refs": ["artifact-raw"],
        }
    )


def _result(
    run_ref: CapabilityRunRef,
    *,
    status: CapabilityRunStatus = CapabilityRunStatus.COMPLETED,
    outcome: CapabilityOutcomeCategory = CapabilityOutcomeCategory.SUCCESS,
    observations: tuple[Observation, ...] = (),
    artifacts: tuple[ArtifactDescriptor, ...] = (),
    code: str = "TEST_RESULT",
) -> CapabilityResult:
    return CapabilityResult(
        run_ref=run_ref,
        execution_status=status,
        outcome=CapabilityOutcome(category=outcome, code=code),
        observations=observations,
        artifacts=artifacts,
    )


def test_result_receipt_round_trip_duplicate_and_conflict(database: CoreDatabase) -> None:
    run = _setup_run(database)
    service = ResultIngestionService(database, clock=lambda: NOW)
    result = _result(run.run_id, outcome=CapabilityOutcomeCategory.NEGATIVE).model_copy(
        update={
            "diagnostics": (
                Diagnostic(
                    code="AUDIT_DIAGNOSTIC",
                    severity=DiagnosticSeverity.INFO,
                    message="Preserved in the complete Result envelope.",
                    occurred_at=NOW,
                    run_ref=run.run_id,
                    details={"structured": True},
                ),
            )
        }
    )

    first = service.accept_result(
        result,
        transport_message_id="transport-result:run-ingestion",
        source_node_id="node-one",
    )
    duplicate = service.accept_result(result)
    assert first == duplicate
    assert first.status is ResultIngestionStatus.RECEIVED
    assert first.result == result

    conflict = _result(
        run.run_id,
        outcome=CapabilityOutcomeCategory.UNKNOWN,
        code="DIFFERENT_RESULT",
    )
    with pytest.raises(ConflictingResultError):
        service.accept_result(conflict)
    persisted = service.get_ingestion(run.run_id)
    assert persisted is not None
    assert persisted.result == result
    assert persisted.conflict_count == 1
    assert persisted.last_conflict_fingerprint is not None


def test_transport_receipt_is_durable_before_semantic_processing(
    database: CoreDatabase,
) -> None:
    run = _setup_run(database)
    service = ResultIngestionService(database, clock=lambda: NOW)
    result = _result(
        run.run_id,
        observations=(_observation(run.run_id, "observation-delayed-processing"),),
    )
    receiver = CoreTransportReceiver(
        database,
        clock=lambda: NOW,
        result_ingestion=service,
        process_results=False,
    )
    envelope = ResultEnvelope(
        message_id=result_message_id(run.run_id),
        node_id="node-delayed-processing",
        correlation_id=run.run_id,
        timestamp=NOW,
        outbox_sequence=1,
        result=result,
    )

    receiver.accept(serialize_message(envelope))
    durable = service.get_ingestion(run.run_id)
    assert durable is not None and durable.status is ResultIngestionStatus.RECEIVED
    with database.unit_of_work() as work:
        assert work.observations.get(result.observations[0].observation_id) is None
        persisted_run = work.runs.get(run.run_id)
    assert persisted_run is not None and persisted_run.status is CapabilityRunStatus.CREATED

    processed = service.process_ingestion(run.run_id)
    assert processed.status is ResultIngestionStatus.PROCESSED


@pytest.mark.parametrize(
    ("execution_status", "outcome"),
    (
        (CapabilityRunStatus.COMPLETED, CapabilityOutcomeCategory.SUCCESS),
        (CapabilityRunStatus.COMPLETED, CapabilityOutcomeCategory.NEGATIVE),
        (CapabilityRunStatus.COMPLETED, CapabilityOutcomeCategory.UNKNOWN),
        (CapabilityRunStatus.FAILED, CapabilityOutcomeCategory.UNKNOWN),
        (CapabilityRunStatus.TIMED_OUT, CapabilityOutcomeCategory.UNKNOWN),
        (CapabilityRunStatus.CANCELLED, CapabilityOutcomeCategory.UNKNOWN),
    ),
)
def test_terminal_status_and_semantic_outcome_are_preserved(
    database: CoreDatabase,
    execution_status: CapabilityRunStatus,
    outcome: CapabilityOutcomeCategory,
) -> None:
    run = _setup_run(database, f"run-{execution_status.value.lower()}-{outcome.value.lower()}")
    service = ResultIngestionService(database, clock=lambda: NOW + timedelta(seconds=5))
    result = _result(run.run_id, status=execution_status, outcome=outcome)
    service.accept_result(result, received_at=NOW + timedelta(seconds=1))
    ingestion = service.process_ingestion(run.run_id)

    assert ingestion.status is ResultIngestionStatus.PROCESSED
    assert ingestion.result.outcome.category is outcome
    with database.unit_of_work() as work:
        stored_run = work.runs.get(run.run_id)
    assert stored_run is not None
    assert stored_run.status is execution_status
    assert stored_run.finished_at == NOW + timedelta(seconds=1)


def test_multi_observation_partial_processing_and_provenance(database: CoreDatabase) -> None:
    run = _setup_run(database)
    artifact = _artifact(run.run_id)
    valid = _observation(run.run_id, "observation-valid", port=22)
    unsupported = _observation(
        run.run_id,
        "observation-future",
        observation_type="future.semantic.fact",
        value={"meaning": "preserve me"},
    )
    invalid = _observation(
        run.run_id,
        "observation-invalid",
        port=80,
        value={"transport": "tcp", "port": 70000, "state": "open"},
    )
    service = ResultIngestionService(database, clock=lambda: NOW)
    result = _result(
        run.run_id,
        observations=(valid, unsupported, invalid),
        artifacts=(artifact,),
    )
    service.accept_result(result)
    ingestion = service.process_ingestion(run.run_id)

    assert ingestion.status is ResultIngestionStatus.PARTIALLY_PROCESSED
    assert (
        ingestion.materialized_count,
        ingestion.unsupported_count,
        ingestion.rejected_count,
    ) == (
        1,
        1,
        1,
    )
    with database.unit_of_work() as work:
        stored_artifact = work.artifacts.get_record(artifact.artifact_id)
        valid_stored = work.observations.get(valid.observation_id)
        future_stored = work.observations.get(unsupported.observation_id)
        invalid_stored = work.observations.get(invalid.observation_id)
        services = work.services.list_for_asset(ASSET)
    assert stored_artifact is not None
    assert stored_artifact.content_state is ArtifactContentState.METADATA_ONLY
    assert valid_stored is not None and valid_stored.observation.evidence_refs == (
        artifact.artifact_id,
    )
    assert future_stored is not None and future_stored.materialization_status.value == "UNSUPPORTED"
    assert invalid_stored is not None and invalid_stored.materialization_status.value == "REJECTED"
    assert len(services) == 1
    assert services[0].current_observation_ref == valid.observation_id
    assert services[0].provenance_refs == (valid.observation_id,)

    assert service.process_ingestion(run.run_id) == ingestion
    with database.unit_of_work() as work:
        assert len(work.services.list_for_asset(ASSET)) == 1


def test_unknown_run_and_observation_identity_conflict_are_rejected(
    database: CoreDatabase,
) -> None:
    service = ResultIngestionService(database, clock=lambda: NOW)
    unknown_ref = CapabilityRunRef("run-unknown")
    service.accept_result(_result(unknown_ref))
    rejected = service.process_ingestion(unknown_ref)
    assert rejected.status is ResultIngestionStatus.REJECTED
    assert rejected.error is not None and "will not fabricate" in rejected.error

    run = _setup_run(database)
    original = _observation(run.run_id, "observation-conflict", port=22)
    changed = _observation(run.run_id, "observation-conflict", port=80)
    with database.unit_of_work() as work:
        work.observations.append(original)
    service.accept_result(_result(run.run_id, observations=(changed,)))
    conflict = service.process_ingestion(run.run_id)
    assert conflict.status is ResultIngestionStatus.REJECTED
    with database.unit_of_work() as work:
        stored = work.observations.get(original.observation_id)
        assert stored is not None and stored.observation == original
        assert work.services.list_for_asset(ASSET) == ()


def test_received_result_recovers_after_core_restart(database_path: Path) -> None:
    first = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(first)
    run = _setup_run(first)
    artifact = _artifact(run.run_id)
    observation = _observation(run.run_id, "observation-recovery")
    receiver = ResultIngestionService(first, clock=lambda: NOW)
    receiver.accept_result(_result(run.run_id, observations=(observation,), artifacts=(artifact,)))
    first.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(reopened)
    try:
        recovered = ResultIngestionService(reopened, clock=lambda: NOW + timedelta(seconds=10))
        processed = recovered.process_pending()
        assert len(processed) == 1
        assert processed[0].status is ResultIngestionStatus.PROCESSED
        with reopened.unit_of_work() as work:
            assert work.observations.get(observation.observation_id) is not None
            services = work.services.list_for_asset(ASSET)
            assert len(services) == 1
            assert services[0].provenance_refs == (observation.observation_id,)
    finally:
        reopened.dispose()


def test_later_result_updates_service_without_losing_observation_history(
    database: CoreDatabase,
) -> None:
    first_run = _setup_run(database, "run-service-first")
    second_run = CapabilityRun(
        run_id=CapabilityRunRef("run-service-second"),
        capability_id=first_run.capability_id,
        operation=first_run.operation,
        mission_ref=first_run.mission_ref,
        status=CapabilityRunStatus.CREATED,
        created_at=NOW + timedelta(seconds=10),
    )
    with database.unit_of_work() as work:
        work.runs.add(second_run)
    first = _observation(first_run.run_id, "observation-service-first", port=445)
    later = _observation(
        second_run.run_id,
        "observation-service-later",
        port=445,
        value={"transport": "tcp", "port": 445, "state": "filtered"},
        observed_offset=10,
    )
    service = ResultIngestionService(database, clock=lambda: NOW + timedelta(seconds=20))
    service.accept_result(_result(first_run.run_id, observations=(first,)))
    service.process_ingestion(first_run.run_id)
    service.accept_result(_result(second_run.run_id, observations=(later,)))
    service.process_ingestion(second_run.run_id)

    with database.unit_of_work() as work:
        materialized = work.services.list_for_asset(ASSET)
        assert work.observations.get(first.observation_id) is not None
        assert work.observations.get(later.observation_id) is not None
    assert len(materialized) == 1
    assert materialized[0].state == "filtered"
    assert materialized[0].current_observation_ref == later.observation_id
    assert set(materialized[0].provenance_refs) == {
        first.observation_id,
        later.observation_id,
    }


def test_artifact_identity_conflict_rejects_result_and_preserves_catalog(
    database: CoreDatabase,
) -> None:
    run = _setup_run(database)
    original = _artifact(run.run_id)
    conflict = original.model_copy(update={"sha256": "b" * 64})
    with database.unit_of_work() as work:
        work.artifacts.add(original)
    service = ResultIngestionService(database, clock=lambda: NOW)
    service.accept_result(_result(run.run_id, artifacts=(conflict,)))
    ingestion = service.process_ingestion(run.run_id)

    assert ingestion.status is ResultIngestionStatus.REJECTED
    with database.unit_of_work() as work:
        stored = work.artifacts.get(original.artifact_id)
        persisted_run = work.runs.get(run.run_id)
    assert stored == original
    assert persisted_run is not None and persisted_run.status is CapabilityRunStatus.CREATED


def test_result_source_must_match_persisted_routing_provenance(database: CoreDatabase) -> None:
    run = _setup_run(database)
    registry = CapabilityRegistry(database, clock=lambda: NOW)
    definition = capability_definition().model_copy(
        update={"capability_id": "network.service_discovery"}
    )
    provider = registry.register_or_refresh_node(
        advertisement("node-expected", definitions=(definition,), timestamp=NOW)
    )[0]
    registry.record_routing_decision(
        RoutingDecision(
            run_ref=run.run_id,
            capability_id=run.capability_id,
            operation=run.operation,
            provider_id=provider.provider_id,
            node_id=provider.node_id,
            implementation_version=provider.implementation_version,
            selected_at=NOW,
        )
    )
    service = ResultIngestionService(database, clock=lambda: NOW)
    service.accept_result(_result(run.run_id), source_node_id="node-unexpected")

    rejected = service.process_ingestion(run.run_id)
    assert rejected.status is ResultIngestionStatus.REJECTED
    assert rejected.error is not None and "source Node" in rejected.error
