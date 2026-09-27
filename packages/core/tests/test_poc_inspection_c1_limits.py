"""C1 enforces its own bounds and reconciles missing structural evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.inspections import (
    CorePoCInspectionService,
    InspectionLimits,
    InspectionStatus,
    PoCInspection,
)
from boberagent_core.inspections.evidence import InspectionError
from boberagent_core.inspections.service import CitationSpan
from test_poc_inspection_c1 import CONTENT, _manifest, _setup, _zip


def _new_with_limits(
    database: CoreDatabase, tmp_path: Path, limits: InspectionLimits
) -> tuple[CorePoCInspectionService, PoCInspection, PoCInspection]:
    service, requested, _ = _setup(database, tmp_path)
    limited = service.create(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=("source.py",),
        limits=limits,
    )
    return service, requested, limited


@pytest.mark.parametrize(
    ("limits", "reason"),
    [
        (InspectionLimits(max_manifest_bytes=1), "INSPECTION_LIMIT_EXCEEDED"),
        (InspectionLimits(max_total_verified_bytes=1), "INSPECTION_LIMIT_EXCEEDED"),
        (InspectionLimits(max_wall_seconds=1e-9), "INSPECTION_LIMIT_EXCEEDED"),
    ],
)
def test_independent_limits_fail_closed(
    database: CoreDatabase, tmp_path: Path, limits: InspectionLimits, reason: str
) -> None:
    service, _requested, limited = _new_with_limits(database, tmp_path, limits)
    failed = service.inspect(limited.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == reason


def test_citation_length_and_count_are_bounded(database: CoreDatabase, tmp_path: Path) -> None:
    service, original, limited = _new_with_limits(
        database, tmp_path, InspectionLimits(max_citation_bytes=1, max_citations=1)
    )
    failed = service.inspect(
        limited.inspection_ref,
        spans=(CitationSpan(path="source.py", start=0, end=2, reader_id="c1", reader_version="1"),),
    )
    assert failed.diagnostic == "CITATION_INVALID"
    count_limited = service.create(
        mission_ref=original.mission_ref,
        hypothesis_ref=original.hypothesis_ref,
        candidate_ref=original.candidate_ref,
        acquisition_ref=original.acquisition_ref,
        selected_paths=("source.py",),
        limits=InspectionLimits(max_citations=1),
    )
    failed_count = service.inspect(
        count_limited.inspection_ref,
        spans=(
            CitationSpan(path="source.py", start=0, end=1, reader_id="c1", reader_version="1"),
            CitationSpan(path="source.py", start=1, end=2, reader_id="c1", reader_version="1"),
        ),
    )
    assert failed_count.diagnostic == "INSPECTION_LIMIT_EXCEEDED"


def test_missing_zip_entry_rejected(database: CoreDatabase, tmp_path: Path) -> None:
    raw = _zip()
    manifest = _manifest(raw, {"source.py": CONTENT, "ghost.py": b"ghost"})
    service, requested, _ = _setup(database, tmp_path, raw=raw, manifest_change=manifest)
    assert service.inspect(requested.inspection_ref).diagnostic == "ZIP_MANIFEST_MISMATCH"


def test_current_artifact_size_mismatch_is_not_accepted(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested, _ = _setup(database, tmp_path)
    digest = requested.raw_sha256
    path = tmp_path / "artifacts" / "content" / "sha256" / digest[:2] / f"{digest}.blob"
    path.write_bytes(path.read_bytes() + b"X")
    assert service.inspect(requested.inspection_ref).diagnostic == "SOURCE_SIZE_MISMATCH"


def test_invalid_selected_path_rejected_before_persistence(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested, _ = _setup(database, tmp_path)
    with pytest.raises(InspectionError, match="INSPECTION_CONFIG_INVALID"):
        service.create(
            mission_ref=requested.mission_ref,
            hypothesis_ref=requested.hypothesis_ref,
            candidate_ref=requested.candidate_ref,
            acquisition_ref=requested.acquisition_ref,
            selected_paths=("../escape",),
        )
