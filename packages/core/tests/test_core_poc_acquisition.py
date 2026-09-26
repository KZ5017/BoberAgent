"""M20-B1 Core acquisition decisions and finalization; no network or source parsing."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    AssetRef,
    CapabilityDefinition,
    CapabilityInvocation,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    Observation,
    ObservationRef,
    PoCAcquisitionBounds,
    PoCAcquisitionRef,
    PoCSourceAcquisitionInput,
    PoCSourceAcquisitionReceipt,
    StorageRef,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    Asset,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    Mission,
    ResultIngestionService,
    upgrade_database,
)
from boberagent_core.acquisitions import (
    CorePoCAcquisitionService,
    PoCAcquisitionError,
    PoCAcquisitionStatus,
)
from boberagent_core.capabilities import (
    CapabilityProvider,
    ProviderAvailability,
    ProviderReportedStatus,
    RoutingDecision,
    provider_id_for,
)
from boberagent_core.research import (
    CoreResearchService,
    DeterministicResearchProvider,
    HitDecision,
    ResearchResponseStatus,
    ResearchResult,
    SourceClass,
    SourceHit,
    VulnerabilityHypothesis,
)
from boberagent_core.research.models import PoCCandidateRef
from pydantic import ValidationError

NOW = datetime(2026, 9, 26, tzinfo=UTC)
RAW = b"offline raw source bytes; not a ZIP"
MANIFEST = b'{"representation_version":1,"files":[]}'
NODE_ID = "node-acquisition-fixture"
PROVIDER_ID = provider_id_for(NODE_ID, "poc.source_acquisition")


def _bounds() -> PoCAcquisitionBounds:
    return PoCAcquisitionBounds(
        max_download_bytes=1024,
        max_uncompressed_bytes=2048,
        max_single_file_bytes=1024,
        max_file_count=10,
        max_directory_depth=5,
        max_path_length=255,
        max_compression_ratio=100,
        max_outbound_requests=3,
        max_redirects=1,
        timeout_seconds=30,
    )


def _components(
    database: CoreDatabase, tmp_path: Path
) -> tuple[CorePoCAcquisitionService, FilesystemArtifactStorage, CoreArtifactService]:
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "artifact-store")
    )
    artifacts = CoreArtifactService(database, storage)
    return CorePoCAcquisitionService(database, artifacts, clock=lambda: NOW), storage, artifacts


def _seed(
    database: CoreDatabase, *, mission_suffix: str = "main"
) -> tuple[CoreResearchService, PoCCandidateRef, tuple[int, int], VulnerabilityHypothesis]:
    mission_ref = MissionRef(f"mission-acquisition-{mission_suffix}")
    asset = Asset(
        asset_ref=AssetRef(f"asset-acquisition-{mission_suffix}"),
        mission_ref=mission_ref,
        kind="host",
        primary_address="192.0.2.20",
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.missions.add(Mission(mission_ref=mission_ref, status="ACTIVE", created_at=NOW))
        work.assets.add(asset)
    research = CoreResearchService(database, clock=lambda: NOW)
    hypothesis = research.create_hypothesis(
        mission_ref=mission_ref,
        asset_ref=asset.asset_ref,
        claim="Example service may be affected by CVE-2026-1234",
        provenance="offline fixture",
        vulnerability_ids=("CVE-2026-1234",),
    )
    uri = f"https://github.com/example/repo-{mission_suffix}"

    def hit(ref: str) -> SourceHit:
        return SourceHit(
            source_class=SourceClass.REPOSITORY,
            source_uri=uri,
            repository_identity=uri,
            revision_claim=ref,
            provider_result_id="42",
            vulnerability_ids=("CVE-2026-1234",),
            match_excerpt="CVE-2026-1234",
        )

    provider = DeterministicResearchProvider(
        "fixture-github-metadata",
        (
            ResearchResult(
                status=ResearchResponseStatus.COMPLETE,
                hits=(hit("branch:old"), hit("branch:new")),
            ),
        ),
    )
    attempt = asyncio.run(research.research(hypothesis.hypothesis_ref, provider, result_limit=2))
    hits = research.list_hits(attempt.attempt_ref)
    assert len(hits) == 2
    assert hits[0].candidate_ref == hits[1].candidate_ref
    assert hits[0].decision is HitDecision.NEW
    assert hits[1].decision is HitDecision.DUPLICATE
    assert hits[0].candidate_ref is not None
    return research, hits[0].candidate_ref, (hits[0].hit_id, hits[1].hit_id), hypothesis


def _definition() -> CapabilityDefinition:
    root = Path(__file__).resolve().parents[3]
    return CapabilityDefinition.model_validate(
        json.loads(
            (root / "docs/m20/poc_source_acquisition.definition.json").read_text(encoding="utf-8")
        )
    )


def _dispatch(
    database: CoreDatabase,
    service: CorePoCAcquisitionService,
    acquisition_ref: PoCAcquisitionRef,
    *,
    run_ref: CapabilityRunRef | None = None,
) -> CapabilityInvocation:
    run_ref = run_ref or CapabilityRunRef("run-acquire")
    invocation = service.build_invocation(acquisition_ref, run_ref)
    with database.unit_of_work() as work:
        work.capability_providers.upsert(
            CapabilityProvider(
                provider_id=PROVIDER_ID,
                node_id=NODE_ID,
                definition=_definition(),
                reported_status=ProviderReportedStatus.AVAILABLE,
                availability=ProviderAvailability.AVAILABLE,
                first_registered_at=NOW,
                last_seen_at=NOW,
                node_lifecycle="READY",
                node_database_ready=True,
            )
        )
        work.runs.add(
            CapabilityRun(
                run_id=run_ref,
                mission_ref=invocation.mission_ref,
                capability_id=invocation.capability_id,
                operation=invocation.operation,
                status=CapabilityRunStatus.CREATED,
                created_at=NOW,
            )
        )
        work.routing_decisions.add(
            RoutingDecision(
                run_ref=run_ref,
                capability_id=invocation.capability_id,
                operation=invocation.operation,
                provider_id=PROVIDER_ID,
                node_id=NODE_ID,
                implementation_version="0.0.0+planned",
                selected_at=NOW,
            )
        )
    dispatched = service.record_dispatched(acquisition_ref, run_ref)
    assert dispatched.status is PoCAcquisitionStatus.DISPATCHED
    assert service.record_dispatched(acquisition_ref, run_ref) == dispatched
    return invocation


def _descriptor(run_ref: CapabilityRunRef, ref: str, data: bytes) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=ArtifactRef(ref),
        artifact_type="poc.source.raw" if ref.endswith("raw") else "poc.source.manifest",
        storage_ref=StorageRef(f"node:{ref}"),
        created_by_run=run_ref,
        created_at=NOW,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        media_type="application/zip" if ref.endswith("raw") else "application/json",
    )


def _receipt(invocation: CapabilityInvocation) -> PoCSourceAcquisitionReceipt:
    inputs = PoCSourceAcquisitionInput.model_validate(invocation.inputs)
    raw = _descriptor(invocation.run_id, "artifact-acquisition-raw", RAW)
    manifest = _descriptor(invocation.run_id, "artifact-acquisition-manifest", MANIFEST)
    assert raw.sha256 is not None
    assert manifest.sha256 is not None
    return PoCSourceAcquisitionReceipt(
        acquisition_ref=inputs.acquisition_ref,
        run_ref=invocation.run_id,
        source_kind=inputs.source_kind,
        repository_uri=inputs.repository_uri,
        provider_repository_id=inputs.provider_repository_id,
        historical_ref=inputs.historical_ref,
        resolved_commit_sha="a" * 40,
        resolved_at=NOW,
        resolution_uri="https://api.github.com/repos/example/repo/commits/old",
        final_archive_uri="https://codeload.github.com/example/repo/zip/sha",
        archive_representation="github_zip",
        adapter_id="offline-fixture",
        adapter_version="1.0",
        request_count=2,
        redirect_count=1,
        raw_source=raw,
        raw_archive_sha256=raw.sha256,
        raw_archive_size_bytes=len(RAW),
        manifest=manifest,
        manifest_sha256=manifest.sha256,
    )


def _persist_result(
    database: CoreDatabase,
    receipt: PoCSourceAcquisitionReceipt,
    *,
    observations: tuple[object, ...] = (),
) -> None:
    assert not observations
    result = CapabilityResult(
        run_ref=receipt.run_ref,
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.SUCCESS,
            details={"acquisition_receipt": receipt.model_dump(mode="json")},
        ),
        artifacts=(receipt.raw_source, receipt.manifest),
    )
    ingestion = ResultIngestionService(database, clock=lambda: NOW)
    ingestion.accept_result(result, source_node_id=NODE_ID)
    assert ingestion.process_ingestion(receipt.run_ref).status.value == "PROCESSED"


def _publish(
    database: CoreDatabase,
    storage: FilesystemArtifactStorage,
    descriptor: ArtifactDescriptor,
    data: bytes,
) -> None:
    transfer_id = f"offline-{descriptor.artifact_id}"
    storage.reconcile_transfer(transfer_id, 0)
    with database.unit_of_work() as work:
        work.artifacts.prepare_transfer(
            descriptor,
            source_node_id=NODE_ID,
            transfer_id=transfer_id,
        )
    offset = storage.append_chunk(
        transfer_id,
        offset=0,
        data=data,
        durable_offset=0,
        declared_size=len(data),
    )
    with database.unit_of_work() as work:
        work.artifacts.set_transfer_progress(descriptor.artifact_id, offset)
    assert descriptor.sha256 is not None
    storage.verify_temporary(transfer_id, digest=descriptor.sha256, size=len(data))
    key, _ = storage.publish(transfer_id, digest=descriptor.sha256, size=len(data))
    with database.unit_of_work() as work:
        work.artifacts.complete_transfer(descriptor.artifact_id, key)


def test_explicit_selected_hit_and_restart_safe_history(
    database_path: Path, tmp_path: Path
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    first = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    second = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[1],
        bounds=_bounds(),
    )
    assert first.acquisition_ref != second.acquisition_ref
    assert (first.historical_ref, second.historical_ref) == ("branch:old", "branch:new")
    assert first.status is PoCAcquisitionStatus.REQUESTED
    assert {item.acquisition_ref: item for item in service.list_for_candidate(candidate_ref)} == {
        first.acquisition_ref: first,
        second.acquisition_ref: second,
    }
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        again, _storage, _artifacts = _components(reopened, tmp_path)
        assert again.get(first.acquisition_ref) == first
        assert again.get(second.acquisition_ref) == second
    finally:
        reopened.dispose()


def test_foreign_rejected_and_missing_hits_are_not_selectable(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    _other_research, other_candidate, other_hits, other_hypothesis = _seed(
        database, mission_suffix="other"
    )
    for hit_id in (0, 999_999, other_hits[0]):
        with pytest.raises(PoCAcquisitionError):
            service.create_acquisition(
                mission_ref=hypothesis.mission_ref,
                hypothesis_ref=hypothesis.hypothesis_ref,
                candidate_ref=candidate_ref,
                selected_hit_id=hit_id,
                bounds=_bounds(),
            )
    with pytest.raises(PoCAcquisitionError):
        service.create_acquisition(
            mission_ref=hypothesis.mission_ref,
            hypothesis_ref=hypothesis.hypothesis_ref,
            candidate_ref=other_candidate,
            selected_hit_id=hit_ids[0],
            bounds=_bounds(),
        )
    with pytest.raises(PoCAcquisitionError):
        service.create_acquisition(
            mission_ref=hypothesis.mission_ref,
            hypothesis_ref=other_hypothesis.hypothesis_ref,
            candidate_ref=candidate_ref,
            selected_hit_id=hit_ids[0],
            bounds=_bounds(),
        )


def test_invocation_builder_and_lifecycle_require_real_routing_records(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    run_ref = CapabilityRunRef("run-acquire")
    invocation = service.build_invocation(acquisition.acquisition_ref, run_ref)
    assert service.build_invocation(acquisition.acquisition_ref, run_ref) == invocation
    assert invocation.capability_id == "poc.source_acquisition"
    assert invocation.operation == "acquire"
    assert (
        PoCSourceAcquisitionInput.model_validate(invocation.inputs).historical_ref == "branch:old"
    )
    with pytest.raises(PoCAcquisitionError):
        service.record_dispatched(acquisition.acquisition_ref, run_ref)
    _dispatch(database, service, acquisition.acquisition_ref)
    with pytest.raises(PoCAcquisitionError):
        service.build_invocation(acquisition.acquisition_ref, CapabilityRunRef("run-different"))
    rejected = service.reject(acquisition.acquisition_ref, "policy rejection")
    assert rejected.status is PoCAcquisitionStatus.REJECTED
    assert service.get(acquisition.acquisition_ref) == rejected


def test_receipt_waits_for_both_artifacts_and_replays_after_reopen(
    database_path: Path, tmp_path: Path
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    service, storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    receipt = _receipt(invocation)
    _persist_result(database, receipt)
    awaiting = service.reconcile(acquisition.acquisition_ref)
    assert awaiting.status is PoCAcquisitionStatus.AWAITING_ARTIFACT
    assert service.reconcile(acquisition.acquisition_ref) == awaiting
    _publish(database, storage, receipt.raw_source, RAW)
    assert (
        service.reconcile(acquisition.acquisition_ref).status
        is PoCAcquisitionStatus.AWAITING_ARTIFACT
    )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        resumed, resumed_storage, artifacts = _components(reopened, tmp_path)
        persisted = resumed.get(acquisition.acquisition_ref)
        assert persisted is not None
        assert persisted.receipt == receipt
        _publish(reopened, resumed_storage, receipt.manifest, MANIFEST)
        completed = resumed.reconcile(acquisition.acquisition_ref)
        assert completed.status is PoCAcquisitionStatus.COMPLETED
        assert completed.resolved_commit_sha == "a" * 40
        assert completed.receipt is not None
        assert completed.receipt.raw_archive_sha256 != completed.resolved_commit_sha
        assert artifacts.read_bytes(receipt.raw_source.artifact_id) == RAW
        assert resumed.reconcile(acquisition.acquisition_ref) == completed
    finally:
        reopened.dispose()


def test_receipt_binding_and_terminal_failure_are_conservative(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    receipt = _receipt(invocation)
    for update in (
        {"historical_ref": "branch:wrong"},
        {"repository_uri": "https://github.com/other/repo"},
        {"provider_repository_id": 777},
        {"request_count": 4},
    ):
        wrong = PoCSourceAcquisitionReceipt.model_validate(
            {**receipt.model_dump(mode="json"), **update}
        )
        with pytest.raises(PoCAcquisitionError):
            persisted = service.get(acquisition.acquisition_ref)
            assert persisted is not None
            service.validate_receipt(persisted, wrong)
    with pytest.raises(ValidationError):
        PoCSourceAcquisitionReceipt.model_validate(
            {**receipt.model_dump(mode="json"), "resolved_commit_sha": "short"}
        )
    for wrong in (
        PoCSourceAcquisitionReceipt.model_validate(
            {**receipt.model_dump(mode="json"), "acquisition_ref": "poc-acquisition-other"}
        ),
        _receipt(invocation.model_copy(update={"run_id": CapabilityRunRef("run-other")})),
    ):
        with pytest.raises(PoCAcquisitionError):
            persisted = service.get(acquisition.acquisition_ref)
            assert persisted is not None
            service.validate_receipt(persisted, wrong)
    rejected = service.reject(acquisition.acquisition_ref, "source identity changed")
    assert rejected.status is PoCAcquisitionStatus.REJECTED
    assert service.reconcile(acquisition.acquisition_ref) == rejected
    with pytest.raises(ValueError):
        service.fail(acquisition.acquisition_ref, "cannot move terminal state")


def test_result_artifact_ref_must_match_receipt(database: CoreDatabase, tmp_path: Path) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    receipt = _receipt(invocation)
    wrong_raw = receipt.raw_source.model_copy(
        update={"artifact_id": ArtifactRef("artifact-wrong-raw")}
    )
    ingestion = ResultIngestionService(database, clock=lambda: NOW)
    ingestion.accept_result(
        CapabilityResult(
            run_ref=invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                details={"acquisition_receipt": receipt.model_dump(mode="json")},
            ),
            artifacts=(wrong_raw, receipt.manifest),
        ),
        source_node_id=NODE_ID,
    )
    assert ingestion.process_ingestion(invocation.run_id).status.value == "PROCESSED"
    assert service.reconcile(acquisition.acquisition_ref).status is PoCAcquisitionStatus.REJECTED


def test_no_implicit_download_or_world_state_write(database: CoreDatabase, tmp_path: Path) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    service.build_invocation(acquisition.acquisition_ref, CapabilityRunRef("run-not-dispatched"))
    with database.unit_of_work() as work:
        assert work.runs.get(CapabilityRunRef("run-not-dispatched")) is None
        assert work.artifacts.get(ArtifactRef("artifact-acquisition-raw")) is None
        assert work.observations.list_pending() == ()
    persisted = service.get(acquisition.acquisition_ref)
    assert persisted is not None
    assert persisted.status is PoCAcquisitionStatus.REQUESTED


@pytest.mark.parametrize(
    ("execution_status", "expected"),
    [
        (CapabilityRunStatus.FAILED, PoCAcquisitionStatus.FAILED),
        (CapabilityRunStatus.CANCELLED, PoCAcquisitionStatus.INTERRUPTED),
        (CapabilityRunStatus.TIMED_OUT, PoCAcquisitionStatus.INTERRUPTED),
    ],
)
def test_terminal_run_result_never_retries(
    database: CoreDatabase,
    tmp_path: Path,
    execution_status: CapabilityRunStatus,
    expected: PoCAcquisitionStatus,
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    result = CapabilityResult(
        run_ref=invocation.run_id,
        execution_status=execution_status,
        outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.UNKNOWN),
    )
    ingestions = ResultIngestionService(database, clock=lambda: NOW)
    ingestions.accept_result(result, source_node_id=NODE_ID)
    ingestions.process_ingestion(invocation.run_id)
    terminal = service.reconcile(acquisition.acquisition_ref)
    assert terminal.status is expected
    assert service.reconcile(acquisition.acquisition_ref) == terminal
    assert terminal.run_ref == invocation.run_id


def test_manifest_alone_cannot_complete_acquisition(database: CoreDatabase, tmp_path: Path) -> None:
    service, storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    receipt = _receipt(invocation)
    _persist_result(database, receipt)
    _publish(database, storage, receipt.manifest, MANIFEST)
    assert (
        service.reconcile(acquisition.acquisition_ref).status
        is PoCAcquisitionStatus.AWAITING_ARTIFACT
    )
    _publish(database, storage, receipt.raw_source, RAW)
    assert service.reconcile(acquisition.acquisition_ref).status is PoCAcquisitionStatus.COMPLETED


def test_acquisition_result_cannot_write_target_world_state(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    observation = Observation(
        observation_id=ObservationRef("observation-illegal-acquisition"),
        type="network.service",
        subject_ref=AssetRef("asset-acquisition-main"),
        value={"transport": "tcp", "port": 80, "state": "open"},
        run_ref=invocation.run_id,
        observed_at=NOW,
    )
    result = CapabilityResult(
        run_ref=invocation.run_id,
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.SUCCESS),
        observations=(observation,),
    )
    ingestions = ResultIngestionService(database, clock=lambda: NOW)
    ingestions.accept_result(result, source_node_id=NODE_ID)
    assert ingestions.process_ingestion(invocation.run_id).status.value == "REJECTED"
    assert service.reconcile(acquisition.acquisition_ref).status is PoCAcquisitionStatus.REJECTED
    with database.unit_of_work() as work:
        assert work.observations.get(observation.observation_id) is None
        assert work.services.list_for_asset(AssetRef("asset-acquisition-main")) == ()


def test_rejected_hit_and_other_candidate_are_not_implicitly_selected(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    research, candidate_ref, _hit_ids, hypothesis = _seed(database)
    provider = DeterministicResearchProvider(
        "fixture-github-metadata",
        (
            ResearchResult(
                status=ResearchResponseStatus.COMPLETE,
                hits=(
                    SourceHit(
                        source_class=SourceClass.REPOSITORY,
                        source_uri="https://github.com/example/other-repo",
                        repository_identity="https://github.com/example/other-repo",
                        revision_claim="branch:main",
                        provider_result_id="45",
                        vulnerability_ids=("CVE-2026-1234",),
                        match_excerpt="CVE-2026-1234",
                    ),
                    SourceHit(
                        source_class=SourceClass.REPOSITORY,
                        source_uri="https://github.com/example/rejected",
                        repository_identity="https://github.com/example/rejected",
                        revision_claim="branch:main",
                        provider_result_id="46",
                        match_excerpt="unrelated issue",
                    ),
                ),
            ),
        ),
    )
    attempt = asyncio.run(research.research(hypothesis.hypothesis_ref, provider, result_limit=2))
    hits = research.list_hits(attempt.attempt_ref)
    assert hits[0].candidate_ref != candidate_ref
    assert hits[1].decision is HitDecision.REJECTED
    for selected in hits:
        with pytest.raises(PoCAcquisitionError):
            service.create_acquisition(
                mission_ref=hypothesis.mission_ref,
                hypothesis_ref=hypothesis.hypothesis_ref,
                candidate_ref=candidate_ref,
                selected_hit_id=selected.hit_id,
                bounds=_bounds(),
            )


def test_conflicting_artifact_metadata_rejects_acquisition_without_overwrite(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    receipt = _receipt(invocation)
    conflicting = receipt.raw_source.model_copy(update={"sha256": "d" * 64})
    with database.unit_of_work() as work:
        work.artifacts.add(conflicting)
    result = CapabilityResult(
        run_ref=invocation.run_id,
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.SUCCESS,
            details={"acquisition_receipt": receipt.model_dump(mode="json")},
        ),
        artifacts=(receipt.raw_source, receipt.manifest),
    )
    ingestions = ResultIngestionService(database, clock=lambda: NOW)
    ingestions.accept_result(result, source_node_id=NODE_ID)
    assert ingestions.process_ingestion(invocation.run_id).status.value == "REJECTED"
    assert service.reconcile(acquisition.acquisition_ref).status is PoCAcquisitionStatus.REJECTED
    with database.unit_of_work() as work:
        stored = work.artifacts.get(receipt.raw_source.artifact_id)
        assert stored is not None
        assert stored.sha256 == "d" * 64
