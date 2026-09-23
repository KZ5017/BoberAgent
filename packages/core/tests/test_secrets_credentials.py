"""Canonical Secret storage and deterministic Credential materialization tests."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    Observation,
    ObservationRef,
    SecretRef,
    StorageRef,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    CoreCredentialService,
    CoreDatabase,
    CoreSecretService,
    FilesystemArtifactStorage,
    MaterializationStatus,
    Mission,
    ReducerRegistry,
    SecretAccessDenied,
    SecretStatus,
)
from conftest import NOW, add_artifact, add_mission_and_run

TEST_SECRET = b"Summer2026!"


def _stored_secret(database: CoreDatabase) -> tuple[CapabilityRun, SecretRef]:
    run = add_mission_and_run(database)
    artifact = add_artifact(database, run)
    secret = CoreSecretService(database, clock=lambda: NOW).store(
        mission_ref=run.mission_ref,
        value=TEST_SECRET,
        secret_type="password",
        created_by_run_ref=run.run_id,
        source_artifact_refs=(artifact.artifact_id,),
        metadata={"format": "text"},
        secret_ref=SecretRef("secret-test-password"),
    )
    return run, secret.secret_ref


def test_secret_storage_metadata_and_explicit_reveal(database: CoreDatabase) -> None:
    run, secret_ref = _stored_secret(database)
    service = CoreSecretService(database, clock=lambda: NOW)

    metadata = service.get(secret_ref)
    assert metadata is not None
    assert metadata.secret_ref == secret_ref
    assert metadata.mission_ref == run.mission_ref
    assert TEST_SECRET.decode() not in metadata.model_dump_json()

    revealed = service.reveal_for_operator(secret_ref, mission_ref=run.mission_ref)
    assert revealed.reveal_bytes() == TEST_SECRET
    assert repr(revealed) == "RevealedSecret(<redacted>)"
    assert str(revealed) == "<redacted>"
    records = service.access_records(secret_ref)
    assert len(records) == 1
    assert records[0].accessor == "OPERATOR"


def test_run_resolution_enforces_mission_ownership(database: CoreDatabase) -> None:
    run, secret_ref = _stored_secret(database)
    other_mission = Mission(
        mission_ref=MissionRef("mission-other"),
        status="ACTIVE",
        created_at=NOW,
    )
    other_run = CapabilityRun(
        run_id=CapabilityRunRef("run-other"),
        capability_id="test.secret_consumer",
        operation="verify",
        mission_ref=other_mission.mission_ref,
        status=CapabilityRunStatus.CREATED,
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.missions.add(other_mission)
        work.runs.add(other_run)

    service = CoreSecretService(database, clock=lambda: NOW)
    assert (
        service.resolve_for_run(
            secret_ref,
            run_ref=run.run_id,
            purpose="test authentication",
        ).reveal_bytes()
        == TEST_SECRET
    )
    with pytest.raises(SecretAccessDenied, match="unavailable"):
        service.resolve_for_run(
            secret_ref,
            run_ref=other_run.run_id,
            purpose="cross-Mission attempt",
        )
    service.set_status(secret_ref, SecretStatus.REVOKED)
    with pytest.raises(SecretAccessDenied, match="unavailable"):
        service.resolve_for_run(
            secret_ref,
            run_ref=run.run_id,
            purpose="revoked value attempt",
        )


def test_candidate_observation_materializes_credential_and_event(
    database: CoreDatabase,
) -> None:
    run, secret_ref = _stored_secret(database)
    with database.unit_of_work() as work:
        artifact = work.artifacts.get(ArtifactRef("artifact-test"))
    assert artifact is not None
    observation = Observation(
        observation_id=ObservationRef("observation-credential-candidate"),
        type="credential.candidate",
        value={
            "credential_type": "username_password",
            "username": "administrator",
            "secrets": [{"role": "password", "secret_ref": str(secret_ref)}],
            "scope_refs": ["asset-auth-target"],
            "metadata": {"realm": "LAB"},
        },
        run_ref=run.run_id,
        observed_at=NOW + timedelta(seconds=1),
        confidence=0.8,
        evidence_refs=(artifact.artifact_id,),
    )
    reducers = ReducerRegistry()
    with database.unit_of_work() as work:
        work.observations.append(observation)
        assert (
            reducers.materialize(observation.observation_id, work)
            is MaterializationStatus.MATERIALIZED
        )
        assert (
            reducers.materialize(observation.observation_id, work)
            is MaterializationStatus.MATERIALIZED
        )

    service = CoreCredentialService(database)
    credentials = service.list_for_mission(run.mission_ref)
    assert len(credentials) == 1
    credential = credentials[0]
    assert credential.username == "administrator"
    assert credential.secrets[0].secret_ref == secret_ref
    assert tuple(str(ref) for ref in credential.scope_refs) == ("asset-auth-target",)
    assert credential.source_observation_refs == (observation.observation_id,)
    assert credential.source_artifact_refs == (artifact.artifact_id,)
    events = service.available_events(run.mission_ref)
    assert len(events) == 1
    assert events[0].type == "credential.available"
    assert events[0].payload["credential_ref"] == str(credential.credential_ref)
    assert TEST_SECRET.decode() not in events[0].model_dump_json()
    assert (
        service.reveal(
            credential.credential_ref,
            role="password",
            mission_ref=run.mission_ref,
        ).reveal_bytes()
        == TEST_SECRET
    )

    earlier = Observation(
        observation_id=ObservationRef("observation-credential-earlier"),
        type="credential.candidate",
        value={
            "credential_type": "username_password",
            "username": "administrator",
            "secrets": [{"role": "password", "secret_ref": str(secret_ref)}],
            "scope_refs": ["asset-other-target"],
            "metadata": {"realm": "LAB"},
        },
        run_ref=run.run_id,
        observed_at=NOW,
        evidence_refs=(artifact.artifact_id,),
    )
    with database.unit_of_work() as work:
        work.observations.append(earlier)
        assert (
            reducers.materialize(earlier.observation_id, work) is MaterializationStatus.MATERIALIZED
        )
    merged = service.list_for_mission(run.mission_ref)
    assert len(merged) == 1
    assert merged[0].credential_ref == credential.credential_ref
    assert merged[0].created_at == NOW
    assert merged[0].updated_at == observation.observed_at
    assert merged[0].source_observation_refs == (
        observation.observation_id,
        earlier.observation_id,
    )
    assert tuple(str(ref) for ref in merged[0].scope_refs) == (
        "asset-auth-target",
        "asset-other-target",
    )
    assert len(service.available_events(run.mission_ref)) == 2

    conflicting = Observation(
        observation_id=ObservationRef("observation-credential-conflict"),
        type="credential.candidate",
        value={
            "credential_type": "username_password",
            "username": "administrator",
            "secrets": [{"role": "password", "secret_ref": str(secret_ref)}],
            "scope_refs": ["asset-should-not-merge"],
            "metadata": {"realm": "DIFFERENT"},
        },
        run_ref=run.run_id,
        observed_at=NOW + timedelta(seconds=2),
        evidence_refs=(artifact.artifact_id,),
    )
    with database.unit_of_work() as work:
        work.observations.append(conflicting)
        assert (
            reducers.materialize(conflicting.observation_id, work) is MaterializationStatus.REJECTED
        )
    assert service.get(credential.credential_ref) == merged[0]
    assert len(service.available_events(run.mission_ref)) == 2


def test_secret_plaintext_is_not_a_normal_result_field(database: CoreDatabase) -> None:
    run, secret_ref = _stored_secret(database)
    result = CapabilityResult(
        run_ref=run.run_id,
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.SUCCESS),
        observations=(
            Observation(
                observation_id=ObservationRef("observation-safe-result"),
                type="credential.candidate",
                value={"secret_ref": str(secret_ref)},
                run_ref=run.run_id,
                observed_at=NOW,
            ),
        ),
    )
    serialized = result.model_dump_json()
    assert str(secret_ref) in serialized
    assert TEST_SECRET.decode() not in serialized


def test_credential_normalization_does_not_rewrite_sensitive_artifact_evidence(
    database: CoreDatabase, tmp_path: Path
) -> None:
    run = add_mission_and_run(database)
    evidence = b"DB_USER=admin\nDB_PASSWORD=secret123\n"
    descriptor = ArtifactDescriptor(
        artifact_id=ArtifactRef("artifact-sensitive-evidence"),
        artifact_type="configuration.raw",
        storage_ref=StorageRef("node-spool:artifact-sensitive-evidence"),
        created_by_run=run.run_id,
        created_at=NOW,
        sha256=hashlib.sha256(evidence).hexdigest(),
        size_bytes=len(evidence),
        media_type="application/octet-stream",
    )
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "artifact-store")
    )
    transfer_id = "transfer-sensitive-evidence"
    with database.unit_of_work() as work:
        work.artifacts.prepare_transfer(
            descriptor,
            source_node_id="node-sensitive-evidence",
            transfer_id=transfer_id,
        )
    assert storage.reconcile_transfer(transfer_id, 0) == 0
    received = storage.append_chunk(
        transfer_id,
        offset=0,
        data=evidence,
        durable_offset=0,
        declared_size=len(evidence),
    )
    storage.verify_temporary(
        transfer_id,
        digest=descriptor.sha256 or "",
        size=len(evidence),
    )
    content_key, _deduplicated = storage.publish(
        transfer_id,
        digest=descriptor.sha256 or "",
        size=len(evidence),
    )
    with database.unit_of_work() as work:
        work.artifacts.set_transfer_progress(descriptor.artifact_id, received)
        work.artifacts.complete_transfer(descriptor.artifact_id, content_key)

    secret = CoreSecretService(database, clock=lambda: NOW).store(
        mission_ref=run.mission_ref,
        value=b"secret123",
        secret_type="password",
        source_artifact_refs=(descriptor.artifact_id,),
    )
    observation = Observation(
        observation_id=ObservationRef("observation-sensitive-evidence"),
        type="credential.candidate",
        value={
            "credential_type": "username_password",
            "username": "admin",
            "secrets": [{"role": "password", "secret_ref": str(secret.secret_ref)}],
        },
        run_ref=run.run_id,
        observed_at=NOW,
        evidence_refs=(descriptor.artifact_id,),
    )
    with database.unit_of_work() as work:
        work.observations.append(observation)
        ReducerRegistry().materialize(observation.observation_id, work)

    assert CoreArtifactService(database, storage).read_bytes(descriptor.artifact_id) == evidence
