"""Independent ZIP/manifest reconciliation and safe extra-field compatibility."""

from __future__ import annotations

import io
import stat
import struct
import zipfile
from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.inspections import InspectionStatus
from boberagent_core.inspections.evidence import InspectionError
from boberagent_core.inspections.service import CitationSpan
from test_poc_inspection_c1 import CONTENT, _manifest, _setup


def _zip_with_extra(extra: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        root = zipfile.ZipInfo("source-root/")
        root.create_system = 3
        root.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(root, b"")
        item = zipfile.ZipInfo("source-root/source.py")
        item.create_system = 3
        item.external_attr = (stat.S_IFREG | 0o644) << 16
        item.extra = extra
        archive.writestr(item, CONTENT)
    return output.getvalue()


def test_github_extended_timestamp_is_structurally_accepted(
    database: CoreDatabase, tmp_path: Path
) -> None:
    extra = struct.pack("<HHBI", 0x5455, 5, 1, 1_700_000_000)
    raw = _zip_with_extra(extra)
    service, requested, _ = _setup(database, tmp_path, raw=raw)
    completed = service.inspect(
        requested.inspection_ref,
        spans=(CitationSpan(path="source.py", start=0, end=1, reader_id="c1", reader_version="1"),),
    )
    assert completed.status is InspectionStatus.COMPLETED


@pytest.mark.parametrize(
    "extra",
    [
        struct.pack("<HH", 0x9999, 0),
        struct.pack("<HHB", 0x5455, 1, 1),
        struct.pack("<HHBI", 0x5455, 5, 1, 1) * 2,
    ],
)
def test_unknown_or_malformed_zip_extra_is_rejected(
    database: CoreDatabase, tmp_path: Path, extra: bytes
) -> None:
    raw = _zip_with_extra(extra)
    service, requested, _ = _setup(database, tmp_path, raw=raw)
    failed = service.inspect(requested.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == "ZIP_INVALID"


def test_directory_cannot_be_cited(database: CoreDatabase, tmp_path: Path) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        root = zipfile.ZipInfo("source-root/")
        root.create_system = 3
        root.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(root, b"")
        directory = zipfile.ZipInfo("source-root/docs/")
        directory.create_system = 3
        directory.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(directory, b"")
        file = zipfile.ZipInfo("source-root/source.py")
        file.create_system = 3
        file.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(file, CONTENT)
    raw = output.getvalue()
    manifest = _manifest(raw)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    entries.insert(
        0,
        {
            "path": "docs",
            "type": "directory",
            "mode": 0o755,
            "executable": None,
            "size_bytes": None,
            "sha256": None,
        },
    )
    manifest["entry_count"] = 2
    service, requested, _ = _setup(database, tmp_path, raw=raw, manifest_change=manifest)
    completed = service.inspect(
        requested.inspection_ref,
        spans=(CitationSpan(path="source.py", start=0, end=1, reader_id="c1", reader_version="1"),),
    )
    assert completed.status is InspectionStatus.COMPLETED
    assert completed.document is not None
    with pytest.raises(InspectionError):
        service.validate_citation(
            completed.inspection_ref,
            completed.document.citations[0].model_copy(update={"path": "docs"}),
        )


def test_duplicate_zip_path_is_rejected(database: CoreDatabase, tmp_path: Path) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("source-root/a.py", CONTENT)
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("source-root/a.py", CONTENT)
    raw = output.getvalue()
    manifest = _manifest(raw, {"a.py": CONTENT})
    service, requested, _ = _setup(database, tmp_path, raw=raw, manifest_change=manifest)
    assert service.inspect(requested.inspection_ref).diagnostic == "ZIP_INVALID"
