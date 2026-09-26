"""Offline M20-B1 decision/receipt/reopen smoke; no source download or ZIP parsing."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    AssetRef,
    CapabilityDefinition,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    PoCAcquisitionBounds,
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
from boberagent_core.acquisitions import CorePoCAcquisitionService, PoCAcquisitionStatus
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
    ResearchResponseStatus,
    ResearchResult,
    SourceClass,
    SourceHit,
)

NOW = datetime(2026, 9, 26, tzinfo=UTC)
NODE_ID = "node-offline-b1-fixture"
RUN = CapabilityRunRef("run-offline-b1")
ROOT = Path(__file__).resolve().parents[2]


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


def _descriptor(ref: str, data: bytes, *, raw: bool) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=ArtifactRef(ref),
        artifact_type="poc.source.raw" if raw else "poc.source.manifest",
        storage_ref=StorageRef(f"node:{ref}"),
        created_by_run=RUN,
        created_at=NOW,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        media_type="application/zip" if raw else "application/json",
    )


def _publish(
    database: CoreDatabase,
    storage: FilesystemArtifactStorage,
    descriptor: ArtifactDescriptor,
    data: bytes,
) -> None:
    transfer_id = f"offline-{descriptor.artifact_id}"
    storage.reconcile_transfer(transfer_id, 0)
    with database.unit_of_work() as work:
        work.artifacts.prepare_transfer(descriptor, source_node_id=NODE_ID, transfer_id=transfer_id)
    offset = storage.append_chunk(
        transfer_id, offset=0, data=data, durable_offset=0, declared_size=len(data)
    )
    with database.unit_of_work() as work:
        work.artifacts.set_transfer_progress(descriptor.artifact_id, offset)
    assert descriptor.sha256 is not None
    storage.verify_temporary(transfer_id, digest=descriptor.sha256, size=len(data))
    content_key, _ = storage.publish(transfer_id, digest=descriptor.sha256, size=len(data))
    with database.unit_of_work() as work:
        work.artifacts.complete_transfer(descriptor.artifact_id, content_key)


def main() -> None:
    with TemporaryDirectory(prefix="boberagent-m20b1-") as temporary:
        root = Path(temporary)
        database_path = root / "core.sqlite3"
        artifact_root = root / "artifacts"
        database = CoreDatabase(DatabaseConfig.sqlite(database_path))
        upgrade_database(database)
        storage = FilesystemArtifactStorage(ArtifactStorageConfiguration(root=artifact_root))
        artifacts = CoreArtifactService(database, storage)
        acquisitions = CorePoCAcquisitionService(database, artifacts, clock=lambda: NOW)
        mission = Mission(
            mission_ref=MissionRef("mission-offline-b1"), status="ACTIVE", created_at=NOW
        )
        asset = Asset(
            asset_ref=AssetRef("asset-offline-b1"),
            mission_ref=mission.mission_ref,
            kind="host",
            primary_address="192.0.2.44",
            created_at=NOW,
        )
        with database.unit_of_work() as work:
            work.missions.add(mission)
            work.assets.add(asset)
        research = CoreResearchService(database, clock=lambda: NOW)
        hypothesis = research.create_hypothesis(
            mission_ref=mission.mission_ref,
            asset_ref=asset.asset_ref,
            claim="Example service might match CVE-2026-1234",
            provenance="offline operator smoke",
            vulnerability_ids=("CVE-2026-1234",),
        )
        uri = "https://github.com/example/offline-repo"

        def hit(branch: str) -> SourceHit:
            return SourceHit(
                source_class=SourceClass.REPOSITORY,
                source_uri=uri,
                repository_identity=uri,
                revision_claim=f"branch:{branch}",
                provider_result_id="42",
                vulnerability_ids=("CVE-2026-1234",),
                match_excerpt="CVE-2026-1234",
            )

        provider = DeterministicResearchProvider(
            "offline-fixture",
            (
                ResearchResult(
                    status=ResearchResponseStatus.COMPLETE,
                    hits=(hit("old"), hit("new")),
                ),
            ),
        )
        attempt = asyncio.run(
            research.research(hypothesis.hypothesis_ref, provider, result_limit=2)
        )
        hits = research.list_hits(attempt.attempt_ref)
        selected = hits[0]
        assert (
            selected.candidate_ref is not None and hits[1].candidate_ref == selected.candidate_ref
        )
        acquisition = acquisitions.create_acquisition(
            mission_ref=mission.mission_ref,
            hypothesis_ref=hypothesis.hypothesis_ref,
            candidate_ref=selected.candidate_ref,
            selected_hit_id=selected.hit_id,
            bounds=_bounds(),
        )
        assert acquisition.status is PoCAcquisitionStatus.REQUESTED
        invocation = acquisitions.build_invocation(acquisition.acquisition_ref, RUN)
        acquisition_input = PoCSourceAcquisitionInput.model_validate(invocation.inputs)
        assert acquisition_input.historical_ref == "branch:old"
        definition = CapabilityDefinition.model_validate(
            json.loads(
                (ROOT / "docs/m20/poc_source_acquisition.definition.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        provider_id = provider_id_for(NODE_ID, definition.capability_id)
        with database.unit_of_work() as work:
            work.capability_providers.upsert(
                CapabilityProvider(
                    provider_id=provider_id,
                    node_id=NODE_ID,
                    definition=definition,
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
                    run_id=RUN,
                    mission_ref=mission.mission_ref,
                    capability_id=definition.capability_id,
                    operation="acquire",
                    status=CapabilityRunStatus.CREATED,
                    created_at=NOW,
                )
            )
            work.routing_decisions.add(
                RoutingDecision(
                    run_ref=RUN,
                    capability_id=definition.capability_id,
                    operation="acquire",
                    provider_id=provider_id,
                    node_id=NODE_ID,
                    implementation_version=definition.implementation_version,
                    selected_at=NOW,
                )
            )
        acquisitions.record_dispatched(acquisition.acquisition_ref, RUN)
        raw_bytes = b"offline synthetic evidence, not downloaded source"
        manifest_bytes = b'{"representation_version":1,"files":[]}'
        raw = _descriptor("artifact-offline-raw", raw_bytes, raw=True)
        manifest = _descriptor("artifact-offline-manifest", manifest_bytes, raw=False)
        assert raw.sha256 is not None and manifest.sha256 is not None
        receipt = PoCSourceAcquisitionReceipt(
            acquisition_ref=acquisition.acquisition_ref,
            run_ref=RUN,
            source_kind="github_repository",
            repository_uri=uri,
            provider_repository_id=42,
            historical_ref="branch:old",
            resolved_commit_sha="a" * 40,
            resolved_at=NOW,
            resolution_uri="https://api.github.com/repos/example/offline-repo/commits/old",
            final_archive_uri="https://codeload.github.com/example/offline-repo/zip/sha",
            archive_representation="github_zip",
            adapter_id="offline-fixture",
            adapter_version="1.0",
            request_count=2,
            redirect_count=1,
            raw_source=raw,
            raw_archive_sha256=raw.sha256,
            raw_archive_size_bytes=len(raw_bytes),
            manifest=manifest,
            manifest_sha256=manifest.sha256,
        )
        result = CapabilityResult(
            run_ref=RUN,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                details={"acquisition_receipt": receipt.model_dump(mode="json")},
            ),
            artifacts=(raw, manifest),
        )
        ingestions = ResultIngestionService(database, clock=lambda: NOW)
        ingestions.accept_result(result, source_node_id=NODE_ID)
        ingestions.process_ingestion(RUN)
        assert (
            acquisitions.reconcile(acquisition.acquisition_ref).status
            is PoCAcquisitionStatus.AWAITING_ARTIFACT
        )
        _publish(database, storage, raw, raw_bytes)
        assert (
            acquisitions.reconcile(acquisition.acquisition_ref).status
            is PoCAcquisitionStatus.AWAITING_ARTIFACT
        )
        _publish(database, storage, manifest, manifest_bytes)
        assert (
            acquisitions.reconcile(acquisition.acquisition_ref).status
            is PoCAcquisitionStatus.COMPLETED
        )
        database.dispose()
        reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
        try:
            reopened_artifacts = CoreArtifactService(
                reopened,
                FilesystemArtifactStorage(ArtifactStorageConfiguration(root=artifact_root)),
            )
            recovered = CorePoCAcquisitionService(reopened, reopened_artifacts)
            final = recovered.get(acquisition.acquisition_ref)
            assert final is not None and final.receipt is not None
            assert final.status is PoCAcquisitionStatus.COMPLETED
            assert final.selected_hit_id == selected.hit_id
            assert final.historical_ref == "branch:old"
            assert final.receipt.resolved_commit_sha == "a" * 40
            assert reopened_artifacts.read_bytes(raw.artifact_id) == raw_bytes
            print(
                f"offline M20-B1 PASS: {final.acquisition_ref} "
                f"{final.historical_ref} {final.status.value}"
            )
        finally:
            reopened.dispose()


if __name__ == "__main__":
    main()
