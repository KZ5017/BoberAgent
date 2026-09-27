"""Hostile structural evidence is rejected without extraction or execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from boberagent_contracts import ArtifactRef
from boberagent_core import CoreDatabase
from boberagent_core.inspections import InspectionLimits, InspectionStatus, SourceCitation
from boberagent_core.inspections.evidence import InspectionError, SourceManifest
from boberagent_core.inspections.service import CitationSpan
from pydantic import ValidationError
from test_poc_inspection_c1 import CONTENT, _manifest, _setup, _zip


def _blob_path(root: Path, digest: str) -> Path:
    return root / "artifacts" / "content" / "sha256" / digest[:2] / f"{digest}.blob"


@pytest.mark.parametrize("which", ["source", "manifest"])
def test_rehash_rejects_mutated_artifact_bytes(
    database: CoreDatabase, tmp_path: Path, which: str
) -> None:
    service, requested, _ = _setup(database, tmp_path)
    digest = requested.raw_sha256 if which == "source" else requested.manifest_sha256
    path = _blob_path(tmp_path, digest)
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    failed = service.inspect(requested.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == f"{'SOURCE' if which == 'source' else 'MANIFEST'}_HASH_MISMATCH"
    assert failed.document is None


def test_corrupt_zip_rejected_after_rehash(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested, _ = _setup(database, tmp_path, raw=b"not a ZIP")
    failed = service.inspect(requested.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == "ZIP_INVALID"


def test_extra_zip_entry_is_not_silently_omitted(database: CoreDatabase, tmp_path: Path) -> None:
    files = {"source.py": CONTENT, "extra.txt": b"evidence"}
    raw = _zip(files)
    manifest = _manifest(raw, {"source.py": CONTENT})
    service, requested, _ = _setup(database, tmp_path, raw=raw, manifest_change=manifest)
    failed = service.inspect(requested.inspection_ref)
    assert failed.diagnostic == "ZIP_MANIFEST_MISMATCH"


def test_manifest_size_and_hash_are_not_zip_authority(
    database: CoreDatabase, tmp_path: Path
) -> None:
    raw = _zip()
    manifest = _manifest(raw)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    entries[0]["size_bytes"] = len(CONTENT) + 1
    manifest["total_uncompressed_bytes"] = len(CONTENT) + 1
    service, requested, _ = _setup(database, tmp_path, manifest_change=manifest)
    assert service.inspect(requested.inspection_ref).diagnostic == "ENTRY_SIZE_MISMATCH"


@pytest.mark.parametrize(
    "entry_change",
    [
        {"sha256": "invalid"},
        {"size_bytes": -1},
        {"size_bytes": True},
        {"path": "../escape"},
        {"path": "un-normalized//path"},
        {"type": "symlink"},
    ],
)
def test_strict_manifest_entry_schema(entry_change: dict[str, object]) -> None:
    raw = _zip()
    manifest = _manifest(raw)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    entries[0].update(entry_change)
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(manifest, strict=True)


def test_duplicate_manifest_path_rejected() -> None:
    raw = _zip()
    manifest = _manifest(raw)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    entries.append(dict(entries[0]))
    manifest["entry_count"] = 2
    manifest["total_uncompressed_bytes"] = len(CONTENT) * 2
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(manifest, strict=True)


def test_selected_entry_limit_fails_but_unselected_is_explicit_coverage(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested, _ = _setup(database, tmp_path)
    limited = service.create(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=("source.py",),
        limits=InspectionLimits(max_entry_bytes=1),
    )
    assert service.inspect(limited.inspection_ref).diagnostic == "INSPECTION_LIMIT_EXCEEDED"
    unselected = service.create(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=(),
        limits=InspectionLimits(max_entry_bytes=1),
    )
    completed = service.inspect(unselected.inspection_ref)
    assert completed.status is InspectionStatus.COMPLETED
    assert completed.document is not None
    assert completed.document.verified_paths == ()
    assert completed.document.unverified_paths == ("source.py",)


def test_citation_rejects_foreign_refs_and_invalid_spans(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested, _ = _setup(database, tmp_path)
    completed = service.inspect(
        requested.inspection_ref,
        spans=(
            CitationSpan(
                path="source.py", start=0, end=len(CONTENT), reader_id="c1", reader_version="1"
            ),
        ),
    )
    assert completed.document is not None
    citation = completed.document.citations[0]
    assert service.read_citation(completed.inspection_ref, citation) == CONTENT
    for update in (
        {"raw_artifact_ref": ArtifactRef("artifact-foreign-raw")},
        {"manifest_artifact_ref": ArtifactRef("artifact-foreign-manifest")},
        {"path": "missing.py"},
    ):
        with pytest.raises(InspectionError):
            service.validate_citation(completed.inspection_ref, citation.model_copy(update=update))
    with pytest.raises(ValidationError):
        CitationSpan(path="source.py", start=3, end=2, reader_id="c1", reader_version="1")
    with pytest.raises(ValidationError):
        CitationSpan(path="source.py", start=-1, end=2, reader_id="c1", reader_version="1")
    with pytest.raises(ValidationError):
        SourceCitation.model_validate({**citation.model_dump(mode="json"), "start": 1, "end": 1})


def test_completed_document_cannot_be_rewritten(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested, _ = _setup(database, tmp_path)
    completed = service.inspect(requested.inspection_ref)
    with database.unit_of_work() as work, pytest.raises(ValueError):
        work.inspections.update(completed.model_copy(update={"status": InspectionStatus.FAILED}))


def test_requested_survives_reopen_and_inspecting_is_interrupted(
    database_path: Path, tmp_path: Path
) -> None:
    from boberagent_core import (
        ArtifactStorageConfiguration,
        CoreArtifactService,
        DatabaseConfig,
        FilesystemArtifactStorage,
        upgrade_database,
    )
    from boberagent_core.inspections import CorePoCInspectionService

    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    service, requested, _ = _setup(database, tmp_path)
    in_progress = service.create(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=(),
    )
    with database.unit_of_work() as work:
        work.inspections.update(
            in_progress.model_copy(
                update={"status": InspectionStatus.INSPECTING, "started_at": requested.created_at}
            )
        )
    database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        artifacts = CoreArtifactService(
            reopened,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
        )
        resumed = CorePoCInspectionService(reopened, artifacts)
        assert resumed.get(requested.inspection_ref) == requested
        assert resumed.recover_interrupted()[0].inspection_ref == in_progress.inspection_ref
        interrupted = resumed.get(in_progress.inspection_ref)
        assert interrupted is not None and interrupted.status is InspectionStatus.INTERRUPTED
        assert resumed.inspect(requested.inspection_ref).status is InspectionStatus.COMPLETED
    finally:
        reopened.dispose()


def test_no_source_tree_is_written(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested, _ = _setup(database, tmp_path)
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert service.inspect(requested.inspection_ref).status is InspectionStatus.COMPLETED
    after = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    assert after == before
