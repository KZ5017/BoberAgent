"""Hostile ZIP fixtures are rejected without extraction or source execution."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path
from typing import cast

import boberagent_capability_poc_source_acquisition.inventory as inventory_module
import pytest
from b2_helpers import SHA, safe_zip, zip_bytes
from boberagent_capability_poc_source_acquisition.errors import AcquisitionRejected
from boberagent_capability_poc_source_acquisition.inventory import inventory_zip
from boberagent_contracts import PoCAcquisitionBounds


def bounds(**updates: int | float) -> PoCAcquisitionBounds:
    base: dict[str, int | float] = {
        "max_download_bytes": 100_000,
        "max_uncompressed_bytes": 20_000,
        "max_single_file_bytes": 10_000,
        "max_file_count": 20,
        "max_directory_depth": 5,
        "max_path_length": 255,
        "max_compression_ratio": 100,
        "max_outbound_requests": 4,
        "max_redirects": 1,
        "timeout_seconds": 10,
    }
    return PoCAcquisitionBounds.model_validate({**base, **updates})


def inventory(
    tmp_path: Path, data: bytes, limits: PoCAcquisitionBounds | None = None
) -> dict[str, object]:
    path = tmp_path / "source.zip"
    path.write_bytes(data)
    result = inventory_zip(
        path,
        limits or bounds(),
        resolved_commit_sha=SHA,
        raw_archive_sha256=hashlib.sha256(data).hexdigest(),
        raw_archive_size_bytes=len(data),
    )
    return cast(dict[str, object], json.loads(result["manifest_bytes"]))


def test_manifest_is_deterministic_and_strips_one_unambiguous_root(tmp_path: Path) -> None:
    data = safe_zip()
    first = inventory(tmp_path, data)
    second = inventory(tmp_path, data)
    assert first == second
    assert first["format_version"] == "poc-source-manifest-v1"
    assert first["archive_root_prefix"] == "fixture-sha/"
    entries = first["entries"]
    assert isinstance(entries, list)
    assert [entry["path"] for entry in entries] == ["README.md", "src/app.py"]
    assert entries[0]["sha256"] == hashlib.sha256(b"harmless evidence\n").hexdigest()
    assert first["total_uncompressed_bytes"] == len(b"harmless evidence\nprint('never executed')\n")


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("../escape", "ARCHIVE_PATH_INVALID"),
        ("/absolute", "ARCHIVE_PATH_INVALID"),
        ("C:/drive", "ARCHIVE_PATH_INVALID"),
        ("\\\\server\\share", "ARCHIVE_PATH_INVALID"),
        ("a\\b", "ARCHIVE_PATH_INVALID"),
        ("a/./b", "ARCHIVE_PATH_INVALID"),
        ("a/../b", "ARCHIVE_PATH_INVALID"),
        ("a//b", "ARCHIVE_PATH_INVALID"),
        ("dir//", "ARCHIVE_PATH_INVALID"),
    ],
)
def test_unsafe_paths_are_rejected(tmp_path: Path, name: str, code: str) -> None:
    data = zip_bytes([(name, b"x", stat.S_IFREG | 0o644)])
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "names",
    [
        ("A.txt", "a.txt"),
        ("é.txt", "e\u0301.txt"),
        ("same.txt", "same.txt"),
        ("file", "file/child"),
    ],
)
def test_collision_rejected(tmp_path: Path, names: tuple[str, str]) -> None:
    data = zip_bytes([(name, b"x", stat.S_IFREG | 0o644) for name in names])
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data)
    assert caught.value.code == "ARCHIVE_COLLISION"


@pytest.mark.parametrize("target", [b"relative.txt", b"../../outside"])
def test_symlink_rejected_even_if_target_looks_internal(tmp_path: Path, target: bytes) -> None:
    data = zip_bytes([("link", target, stat.S_IFLNK | 0o777)])
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data)
    assert caught.value.code == "ARCHIVE_ENTRY_TYPE_UNSUPPORTED"


def test_special_entry_rejected(tmp_path: Path) -> None:
    data = zip_bytes([("pipe", b"", stat.S_IFIFO | 0o644)])
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data)
    assert caught.value.code == "ARCHIVE_ENTRY_TYPE_UNSUPPORTED"


@pytest.mark.parametrize(
    ("update", "code"),
    [
        ({"max_file_count": 2}, "ARCHIVE_LIMIT_EXCEEDED"),
        ({"max_path_length": 5}, "ARCHIVE_PATH_INVALID"),
        ({"max_directory_depth": 1}, "ARCHIVE_PATH_INVALID"),
        ({"max_single_file_bytes": 10}, "ARCHIVE_LIMIT_EXCEEDED"),
        ({"max_uncompressed_bytes": 20, "max_single_file_bytes": 20}, "ARCHIVE_LIMIT_EXCEEDED"),
    ],
)
def test_inventory_limits(tmp_path: Path, update: dict[str, int], code: str) -> None:
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, safe_zip(), bounds(**update))
    assert caught.value.code == code


def test_compression_ratio_rejects_small_bomb_fixture(tmp_path: Path) -> None:
    data = zip_bytes([("bomb", b"0" * 4096, stat.S_IFREG | 0o644)])
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data, bounds(max_compression_ratio=2))
    assert caught.value.code == "ARCHIVE_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "name,content,code",
    [
        (".gitmodules", b"[submodule]\n", "SUBMODULE_UNSUPPORTED"),
        (
            "pointer.bin",
            b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\n",
            "LFS_UNSUPPORTED",
        ),
    ],
)
def test_submodule_and_lfs_are_unsupported(
    tmp_path: Path, name: str, content: bytes, code: str
) -> None:
    data = zip_bytes([(name, content, stat.S_IFREG | 0o644)])
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data)
    assert caught.value.code == code


@pytest.mark.parametrize("data", [b"not a ZIP", safe_zip()[:-10]])
def test_truncated_or_invalid_directory_rejected(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data)
    assert caught.value.code in {"SOURCE_INTEGRITY_INVALID", "ARCHIVE_UNSUPPORTED"}


def test_crc_corruption_is_rejected(tmp_path: Path) -> None:
    data = bytearray(zip_bytes([("file", b"UNIQUE-CONTENT", stat.S_IFREG | 0o644)]))
    # Corrupt compressed bytes after local header without altering the central directory.
    offset = data.index(b"PK\x03\x04") + 30 + len(b"file")
    data[offset] ^= 0xFF
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, bytes(data))
    assert caught.value.code == "SOURCE_INTEGRITY_INVALID"


def test_unsupported_compression_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_BZIP2) as archive:
        info = zipfile.ZipInfo("file")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        info.compress_type = zipfile.ZIP_BZIP2
        archive.writestr(info, b"x")
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, path.read_bytes())
    assert caught.value.code == "ARCHIVE_UNSUPPORTED"


def test_exact_entry_count_path_and_total_bound_are_accepted(tmp_path: Path) -> None:
    data = safe_zip()
    assert (
        inventory(
            tmp_path,
            data,
            bounds(
                max_file_count=3,
                max_path_length=10,
                max_uncompressed_bytes=64,
                max_single_file_bytes=64,
            ),
        )["entry_count"]
        == 2
    )


def test_explicit_directory_is_structural_not_hashed(tmp_path: Path) -> None:
    data = zip_bytes(
        [
            ("root/", b"", stat.S_IFDIR | 0o755),
            ("root/dir/", b"", stat.S_IFDIR | 0o755),
            ("root/dir/file", b"x", stat.S_IFREG | 0o644),
        ]
    )
    manifest = inventory(tmp_path, data)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    assert entries[0] == {
        "path": "dir",
        "type": "directory",
        "mode": 493,
        "executable": None,
        "size_bytes": None,
        "sha256": None,
    }


def test_raw_nul_in_central_name_is_rejected_before_zipfile_truncates_it(tmp_path: Path) -> None:
    data = bytearray(zip_bytes([("file", b"x", stat.S_IFREG | 0o644)]))
    offset = data.index(b"PK\x01\x02") + 46
    data[offset + 1] = 0
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, bytes(data))
    assert caught.value.code == "ARCHIVE_PATH_INVALID"


def test_encrypted_flag_is_rejected_without_attempting_decryption(tmp_path: Path) -> None:
    data = bytearray(zip_bytes([("file", b"x", stat.S_IFREG | 0o644)]))
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    data[local + 6] |= 1
    data[central + 8] |= 1
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, bytes(data))
    assert caught.value.code == "ARCHIVE_UNSUPPORTED"


def test_unreviewed_zip_extra_metadata_is_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("file")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        info.extra = b"\x99\x99\x00\x00"
        archive.writestr(info, b"x")
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, path.read_bytes())
    assert caught.value.code == "ARCHIVE_UNSUPPORTED"


def test_serialized_manifest_size_is_checked_after_json_escaping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inventory_module, "_MAX_MANIFEST_BYTES", 450)
    data = zip_bytes([('"' * 150, b"x", stat.S_IFREG | 0o644)])
    with pytest.raises(AcquisitionRejected) as caught:
        inventory(tmp_path, data)
    assert caught.value.code == "ARCHIVE_LIMIT_EXCEEDED"
