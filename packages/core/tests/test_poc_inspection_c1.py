"""M20-C1 uses only retained synthetic Core Artifacts; never executes source."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest
from boberagent_contracts import PoCAcquisitionBounds, PoCSourceAcquisitionReceipt
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    current_revision,
    upgrade_database,
)
from boberagent_core.acquisitions import CorePoCAcquisitionService, PoCAcquisitionStatus
from boberagent_core.inspections import (
    CorePoCInspectionService,
    InspectionLimits,
    InspectionStatus,
    PoCInspection,
    SourceCitation,
)
from boberagent_core.inspections.evidence import InspectionError, line_span
from boberagent_core.inspections.models import InspectionDocument
from boberagent_core.inspections.service import CitationSpan
from sqlalchemy import inspect
from test_core_poc_acquisition import (
    NOW,
    _bounds,
    _descriptor,
    _dispatch,
    _persist_result,
    _publish,
    _receipt,
    _seed,
)

CONTENT = b"first\r\nsecond\nlast"
COMMIT = "a" * 40


def _zip(files: dict[str, bytes] | None = None) -> bytes:
    files = files or {"source.py": CONTENT}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        root = zipfile.ZipInfo("source-root/")
        root.create_system = 3
        root.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(root, b"")
        for path, content in files.items():
            info = zipfile.ZipInfo("source-root/" + path)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return output.getvalue()


def _manifest(raw: bytes, files: dict[str, bytes] | None = None) -> dict[str, object]:
    files = files or {"source.py": CONTENT}
    return {
        "format_version": "poc-source-manifest-v1",
        "archive_representation": "github_zip",
        "resolved_commit_sha": COMMIT,
        "raw_archive_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_archive_size_bytes": len(raw),
        "archive_root_prefix": "source-root/",
        "entry_count": len(files),
        "total_uncompressed_bytes": sum(len(content) for content in files.values()),
        "entries": [
            {
                "path": path,
                "type": "file",
                "mode": 0o644,
                "executable": False,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in sorted(files.items())
        ],
    }


def _setup(
    database: CoreDatabase,
    tmp_path: Path,
    *,
    raw: bytes | None = None,
    manifest_change: dict[str, object] | None = None,
    files: dict[str, bytes] | None = None,
    bounds: PoCAcquisitionBounds | None = None,
) -> tuple[CorePoCInspectionService, PoCInspection, FilesystemArtifactStorage]:
    raw = raw if raw is not None else _zip(files)
    manifest = _manifest(raw, files)
    manifest.update(manifest_change or {})
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    storage = FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts"))
    artifacts = CoreArtifactService(database, storage)
    acquisition_service = CorePoCAcquisitionService(database, artifacts, clock=lambda: NOW)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    acquisition = acquisition_service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=bounds or _bounds(),
    )
    invocation = _dispatch(database, acquisition_service, acquisition.acquisition_ref)
    original = _receipt(invocation)
    receipt = PoCSourceAcquisitionReceipt.model_validate(
        {
            **original.model_dump(mode="json"),
            "raw_source": _descriptor(invocation.run_id, "artifact-inspection-raw", raw).model_dump(
                mode="json"
            ),
            "raw_archive_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_archive_size_bytes": len(raw),
            "manifest": _descriptor(
                invocation.run_id, "artifact-inspection-manifest", manifest_bytes
            ).model_dump(mode="json"),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }
    )
    _persist_result(database, receipt)
    assert (
        acquisition_service.reconcile(acquisition.acquisition_ref).status
        is PoCAcquisitionStatus.AWAITING_ARTIFACT
    )
    _publish(database, storage, receipt.raw_source, raw)
    _publish(database, storage, receipt.manifest, manifest_bytes)
    assert (
        acquisition_service.reconcile(acquisition.acquisition_ref).status
        is PoCAcquisitionStatus.COMPLETED
    )
    service = CorePoCInspectionService(database, artifacts, clock=lambda: NOW)
    inspection = service.create(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        acquisition_ref=acquisition.acquisition_ref,
        selected_paths=("source.py",),
    )
    return service, inspection, storage


def test_completed_citation_reuse_and_reopen(database_path: Path, tmp_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    service, requested, _storage = _setup(database, tmp_path)
    completed = service.inspect(
        requested.inspection_ref,
        spans=(CitationSpan(path="source.py", start=0, end=5, reader_id="c1", reader_version="1"),),
    )
    assert completed.status is InspectionStatus.COMPLETED
    assert isinstance(completed.document, InspectionDocument)
    assert completed.document.verified_paths == ("source.py",)
    citation = completed.document.citations[0]
    assert service.read_citation(completed.inspection_ref, citation) == b"first"
    assert service.citation_lines(completed.inspection_ref, citation) == (1, 1)
    assert service.inspect(completed.inspection_ref) == completed
    assert (
        service.create(
            mission_ref=completed.mission_ref,
            hypothesis_ref=completed.hypothesis_ref,
            candidate_ref=completed.candidate_ref,
            acquisition_ref=completed.acquisition_ref,
            selected_paths=("source.py",),
        )
        == completed
    )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        artifacts = CoreArtifactService(
            reopened,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
        )
        again = CorePoCInspectionService(reopened, artifacts)
        assert again.get(completed.inspection_ref) == completed
        assert again.read_citation(completed.inspection_ref, citation) == b"first"
    finally:
        reopened.dispose()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"format_version": "future"}, "MANIFEST_INVALID"),
        ({"resolved_commit_sha": "b" * 40}, "MANIFEST_IDENTITY_MISMATCH"),
        ({"raw_archive_sha256": "b" * 64}, "MANIFEST_IDENTITY_MISMATCH"),
        ({"raw_archive_size_bytes": 999}, "MANIFEST_IDENTITY_MISMATCH"),
        ({"entry_count": 2}, "MANIFEST_INVALID"),
        ({"total_uncompressed_bytes": 99}, "MANIFEST_INVALID"),
        ({"archive_root_prefix": "wrong/"}, "ZIP_MANIFEST_MISMATCH"),
        ({"entries": []}, "MANIFEST_INVALID"),
        (
            {
                "entries": [
                    {
                        "path": "other.py",
                        "type": "file",
                        "mode": 420,
                        "executable": False,
                        "size_bytes": len(CONTENT),
                        "sha256": hashlib.sha256(CONTENT).hexdigest(),
                    }
                ]
            },
            "ZIP_MANIFEST_MISMATCH",
        ),
    ],
)
def test_manifest_fail_closed(
    database: CoreDatabase, tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    service, requested, _ = _setup(database, tmp_path, manifest_change=change)
    failed = service.inspect(requested.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == reason
    assert failed.document is None


def test_entry_hash_failure_and_history(database: CoreDatabase, tmp_path: Path) -> None:
    raw = _zip()
    manifest = _manifest(raw)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    entries[0]["sha256"] = "b" * 64
    service, requested, _ = _setup(database, tmp_path, manifest_change=manifest)
    failed = service.inspect(requested.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == "ENTRY_HASH_MISMATCH"
    newer = service.create(
        mission_ref=failed.mission_ref,
        hypothesis_ref=failed.hypothesis_ref,
        candidate_ref=failed.candidate_ref,
        acquisition_ref=failed.acquisition_ref,
        selected_paths=("source.py",),
    )
    assert newer.inspection_ref != failed.inspection_ref
    assert len(service.list_for_acquisition(failed.acquisition_ref)) == 2


def test_profile_config_history_and_recovery(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested, _ = _setup(database, tmp_path)
    with database.unit_of_work() as work:
        inspecting = work.inspections.update(
            requested.model_copy(update={"status": InspectionStatus.INSPECTING, "started_at": NOW})
        )
    assert service.recover_interrupted()[0].status is InspectionStatus.INTERRUPTED
    assert service.recover_interrupted() == ()
    newer = service.create(
        mission_ref=inspecting.mission_ref,
        hypothesis_ref=inspecting.hypothesis_ref,
        candidate_ref=inspecting.candidate_ref,
        acquisition_ref=inspecting.acquisition_ref,
        selected_paths=("source.py",),
        profile_version="2",
    )
    assert newer.inspection_ref != requested.inspection_ref
    changed = service.create(
        mission_ref=inspecting.mission_ref,
        hypothesis_ref=inspecting.hypothesis_ref,
        candidate_ref=inspecting.candidate_ref,
        acquisition_ref=inspecting.acquisition_ref,
        selected_paths=("source.py",),
        limits=InspectionLimits(max_entry_bytes=1024),
    )
    assert changed.config_fingerprint != requested.config_fingerprint


@pytest.mark.parametrize(
    ("data", "span", "expected"),
    [
        (b"a\nb\nlast", (4, 8), (3, 3)),
        (b"a\r\nb\r\nlast", (6, 10), (3, 3)),
        (b"\xef\xbb\xbfhello\nlast", (3, 8), (1, 1)),
        (b"ASCII", (0, 5), (1, 1)),
        (b"\xff\xfe" + "a\nb".encode("utf-16-le"), (2, 4), (1, 1)),
        (b"\xfe\xff" + "a\nb".encode("utf-16-be"), (2, 4), (1, 1)),
        (b"\xff\xff", (0, 2), None),
        (b"\x00\xff", (0, 2), None),
    ],
)
def test_deterministic_line_display(
    data: bytes, span: tuple[int, int], expected: tuple[int, int] | None
) -> None:
    assert line_span(data, *span) == expected


def test_citation_rejects_foreign_identity_and_bounds(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested, _ = _setup(database, tmp_path)
    completed = service.inspect(
        requested.inspection_ref,
        spans=(CitationSpan(path="source.py", start=0, end=5, reader_id="c1", reader_version="1"),),
    )
    assert isinstance(completed.document, InspectionDocument)
    citation = completed.document.citations[0]
    for update in (
        {"raw_sha256": "f" * 64},
        {"manifest_sha256": "f" * 64},
        {"entry_sha256": "f" * 64},
        {"path": "foreign.py"},
        {"end": len(CONTENT) + 1},
    ):
        with pytest.raises(InspectionError):
            service.validate_citation(completed.inspection_ref, citation.model_copy(update=update))
    with pytest.raises(ValueError):
        SourceCitation.model_validate({**citation.model_dump(mode="json"), "start": 5, "end": 5})


def test_migration_from_b_and_fresh(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0011_m20_b3_fixture_mode")
        assert "poc_inspections" not in inspect(database._migration_engine).get_table_names()
        upgrade_database(database)
        assert current_revision(database) == "0014_m20_d5_policy_identity"
        assert "poc_inspections" in inspect(database._migration_engine).get_table_names()
    finally:
        database.dispose()
