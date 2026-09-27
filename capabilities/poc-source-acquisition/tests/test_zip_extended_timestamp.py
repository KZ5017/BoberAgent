"""Real GitHub-style UT ZIP metadata is accepted; all other extras stay fail-closed."""

from __future__ import annotations

import hashlib
import io
import stat
import struct
import zipfile
from pathlib import Path

import pytest
from boberagent_capability_poc_source_acquisition.errors import AcquisitionRejected
from boberagent_capability_poc_source_acquisition.inventory import _validate_zip_extra
from test_inventory import inventory

_UT = struct.pack("<HHBI", 0x5455, 5, 1, 1_700_000_000)


def _github_style_archive(*, timestamp: bool) -> bytes:
    output = io.BytesIO()
    entries = (
        ("repo-commit/", b"", stat.S_IFDIR | 0o755, zipfile.ZIP_STORED),
        ("repo-commit/README.md", b"plain evidence\n", stat.S_IFREG | 0o644, zipfile.ZIP_STORED),
        (
            "repo-commit/src/file.py",
            b"print('not executed')\n",
            stat.S_IFREG | 0o644,
            zipfile.ZIP_DEFLATED,
        ),
    )
    with zipfile.ZipFile(output, "w") as archive:
        for name, content, mode, compression in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compression
            info.extra = _UT if timestamp else b""
            archive.writestr(info, content)
    return output.getvalue()


def test_github_style_ut_metadata_is_structural_only(tmp_path: Path) -> None:
    raw = _github_style_archive(timestamp=True)
    without_timestamp = _github_style_archive(timestamp=False)
    manifest = inventory(tmp_path, raw)
    repeat = inventory(tmp_path, raw)
    plain = inventory(tmp_path, without_timestamp)

    assert manifest == repeat
    assert manifest["archive_root_prefix"] == "repo-commit/"
    assert manifest["entry_count"] == 2
    assert manifest["raw_archive_sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["raw_archive_sha256"] != plain["raw_archive_sha256"]
    assert manifest["entries"] == plain["entries"]
    assert manifest["total_uncompressed_bytes"] == plain["total_uncompressed_bytes"]
    entries = manifest["entries"]
    assert isinstance(entries, list)
    assert [entry["path"] for entry in entries] == ["README.md", "src/file.py"]
    assert entries[0]["sha256"] == hashlib.sha256(b"plain evidence\n").hexdigest()
    assert entries[1]["sha256"] == hashlib.sha256(b"print('not executed')\n").hexdigest()
    assert "timestamp" not in str(manifest).lower()


@pytest.mark.parametrize(
    "extra",
    [
        struct.pack("<HH", 0x9999, 0),
        b"\x55\x54\x05",  # incomplete header
        struct.pack("<HH", 0x5455, 5) + b"\x01\x00",  # declared length too long
        struct.pack("<HH", 0x5455, 0),  # empty UT payload
        struct.pack("<HH", 0x5455, 4) + b"\x01\x00\x00\x00",  # truncated time
        struct.pack("<HHBI", 0x5455, 5, 0x03, 1_700_000_000),  # unsupported flags
        struct.pack("<HHBI", 0x5455, 6, 0x01, 1_700_000_000) + b"\x00",
        _UT + struct.pack("<HH", 0x9999, 0),
        _UT + b"\x55\x54",  # malformed second record
        _UT + struct.pack("<HHBI", 0x5455, 5, 1, 1_700_000_001),  # duplicate
        b"\x00" * 1025,  # total extra bound
    ],
)
def test_unknown_or_malformed_extra_is_rejected(extra: bytes) -> None:
    with pytest.raises(AcquisitionRejected) as caught:
        _validate_zip_extra(extra)
    assert caught.value.code == "ARCHIVE_UNSUPPORTED"


def test_unknown_field_is_rejected_in_full_archive(tmp_path: Path) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("repo-commit/file")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        info.extra = _UT + struct.pack("<HH", 0x9999, 0)
        archive.writestr(info, b"evidence")
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, output.getvalue())
    assert caught.value.code == "ARCHIVE_UNSUPPORTED"
