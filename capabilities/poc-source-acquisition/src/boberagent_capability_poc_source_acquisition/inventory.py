"""Fail-closed structural ZIP inventory; never extracts or executes archive content."""

from __future__ import annotations

import hashlib
import json
import stat
import struct
import unicodedata
import zipfile
import zlib
from pathlib import Path
from typing import Literal, TypedDict

from boberagent_contracts import PoCAcquisitionBounds

from .errors import AcquisitionRejected

_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
_ZIP_END = b"PK\x05\x06"
_READ_SIZE = 64 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class ManifestEntry(TypedDict):
    path: str
    type: Literal["file", "directory"]
    mode: int | None
    executable: bool | None
    size_bytes: int | None
    sha256: str | None


class InventoryResult(TypedDict):
    manifest_bytes: bytes
    entry_count: int
    total_uncompressed_bytes: int
    archive_root_prefix: str | None


def inventory_zip(
    archive_path: Path,
    bounds: PoCAcquisitionBounds,
    *,
    resolved_commit_sha: str,
    raw_archive_sha256: str,
    raw_archive_size_bytes: int,
) -> InventoryResult:
    """Inventory regular entries under actual-byte, path, and collision limits."""

    _preflight_central_directory(archive_path, bounds.max_file_count)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > bounds.max_file_count:
                raise AcquisitionRejected("ARCHIVE_LIMIT_EXCEEDED", "ZIP entry count exceeds bound")
            parsed = [(_normalized_name(info.filename), info) for info in infos]
            _check_collisions(parsed)
            root = _common_root(parsed)
            entries: list[ManifestEntry] = []
            total = 0
            manifest_estimate = 0
            for name, info in parsed:
                if root is not None:
                    if name == root and info.is_dir():
                        continue
                    name = name[len(root) + 1 :]
                _check_path_bounds(name, bounds)
                manifest_estimate += len(name.encode("utf-8")) + 256
                if manifest_estimate > _MAX_MANIFEST_BYTES:
                    raise AcquisitionRejected(
                        "ARCHIVE_LIMIT_EXCEEDED", "structural manifest exceeds bound"
                    )
                if info.extra:
                    raise AcquisitionRejected(
                        "ARCHIVE_UNSUPPORTED", "ZIP extra metadata is unsupported"
                    )
                entry_type, mode = _entry_type(info)
                if info.flag_bits & 1:
                    raise AcquisitionRejected(
                        "ARCHIVE_UNSUPPORTED", "encrypted ZIP entry is unsupported"
                    )
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise AcquisitionRejected(
                        "ARCHIVE_UNSUPPORTED", "ZIP compression method is unsupported"
                    )
                if entry_type == "directory":
                    if info.file_size:
                        raise AcquisitionRejected("ARCHIVE_UNSUPPORTED", "directory has content")
                    entries.append(
                        ManifestEntry(
                            path=name,
                            type="directory",
                            mode=mode,
                            executable=None,
                            size_bytes=None,
                            sha256=None,
                        )
                    )
                    continue
                if name == ".gitmodules" or name.endswith("/.gitmodules"):
                    raise AcquisitionRejected(
                        "SUBMODULE_UNSUPPORTED", "submodule metadata is unsupported"
                    )
                if info.file_size > bounds.max_single_file_bytes:
                    raise AcquisitionRejected(
                        "ARCHIVE_LIMIT_EXCEEDED", "ZIP file exceeds size bound"
                    )
                if total + info.file_size > bounds.max_uncompressed_bytes:
                    raise AcquisitionRejected(
                        "ARCHIVE_LIMIT_EXCEEDED", "ZIP total exceeds size bound"
                    )
                digest = hashlib.sha256()
                size = 0
                prefix = b""
                with archive.open(info) as stream:
                    while chunk := stream.read(_READ_SIZE):
                        size += len(chunk)
                        total += len(chunk)
                        if (
                            size > bounds.max_single_file_bytes
                            or total > bounds.max_uncompressed_bytes
                        ):
                            raise AcquisitionRejected(
                                "ARCHIVE_LIMIT_EXCEEDED", "decompressed ZIP bytes exceed bound"
                            )
                        if size > bounds.max_compression_ratio * max(info.compress_size, 1):
                            raise AcquisitionRejected(
                                "ARCHIVE_LIMIT_EXCEEDED", "ZIP compression ratio exceeds bound"
                            )
                        if len(prefix) < len(_LFS_PREFIX):
                            prefix += chunk[: len(_LFS_PREFIX) - len(prefix)]
                        digest.update(chunk)
                if size != info.file_size:
                    raise AcquisitionRejected(
                        "SOURCE_INTEGRITY_INVALID", "ZIP size claim is invalid"
                    )
                if prefix.startswith(_LFS_PREFIX):
                    raise AcquisitionRejected("LFS_UNSUPPORTED", "Git LFS pointer is unsupported")
                entries.append(
                    ManifestEntry(
                        path=name,
                        type="file",
                        mode=mode,
                        executable=None if mode is None else bool(mode & 0o111),
                        size_bytes=size,
                        sha256=digest.hexdigest(),
                    )
                )
    except AcquisitionRejected:
        raise
    except (
        zipfile.BadZipFile,
        EOFError,
        OSError,
        RuntimeError,
        ValueError,
        NotImplementedError,
        zlib.error,
    ) as error:
        raise AcquisitionRejected(
            "SOURCE_INTEGRITY_INVALID", "ZIP structure or content is invalid"
        ) from error
    entries.sort(key=lambda item: item["path"])
    manifest = {
        "format_version": "poc-source-manifest-v1",
        "archive_representation": "github_zip",
        "resolved_commit_sha": resolved_commit_sha,
        "raw_archive_sha256": raw_archive_sha256,
        "raw_archive_size_bytes": raw_archive_size_bytes,
        "archive_root_prefix": None if root is None else root + "/",
        "entry_count": len(entries),
        "total_uncompressed_bytes": total,
        "entries": entries,
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
        raise AcquisitionRejected("ARCHIVE_LIMIT_EXCEEDED", "structural manifest exceeds bound")
    return InventoryResult(
        manifest_bytes=manifest_bytes,
        entry_count=len(entries),
        total_uncompressed_bytes=total,
        archive_root_prefix=None if root is None else root + "/",
    )


def _preflight_central_directory(path: Path, maximum_entries: int) -> None:
    """Reject an oversized central-directory count before ZipFile builds ZipInfo objects."""

    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read()
    offset = tail.rfind(_ZIP_END)
    if offset < 0 or len(tail) - offset < 22:
        raise AcquisitionRejected("SOURCE_INTEGRITY_INVALID", "ZIP end record is missing")
    (
        _,
        disk,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_size,
    ) = struct.unpack_from("<IHHHHIIH", tail, offset)
    if (
        disk != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or offset + 22 + comment_size != len(tail)
        or central_offset + central_size > size
    ):
        raise AcquisitionRejected("ARCHIVE_UNSUPPORTED", "ZIP directory format is unsupported")
    if total_entries > maximum_entries:
        raise AcquisitionRejected("ARCHIVE_LIMIT_EXCEEDED", "ZIP entry count exceeds bound")
    with path.open("rb") as stream:
        stream.seek(central_offset)
        for _ in range(total_entries):
            header = stream.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise AcquisitionRejected(
                    "SOURCE_INTEGRITY_INVALID", "ZIP central directory is malformed"
                )
            name_size, extra_size, comment_size = struct.unpack_from("<HHH", header, 28)
            raw_name = stream.read(name_size)
            if len(raw_name) != name_size or b"\x00" in raw_name:
                raise AcquisitionRejected("ARCHIVE_PATH_INVALID", "ZIP central path is invalid")
            stream.seek(extra_size + comment_size, 1)
            if stream.tell() > central_offset + central_size:
                raise AcquisitionRejected(
                    "SOURCE_INTEGRITY_INVALID", "ZIP central directory overflows"
                )
        if stream.tell() != central_offset + central_size:
            raise AcquisitionRejected(
                "SOURCE_INTEGRITY_INVALID", "ZIP central directory size disagrees"
            )


def _normalized_name(raw: str) -> str:
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or raw.startswith(("/", "//"))
        or raw.endswith("//")
        or (len(raw) >= 2 and raw[1] == ":")
    ):
        raise AcquisitionRejected("ARCHIVE_PATH_INVALID", "ZIP path is unsafe")
    components = raw.rstrip("/").split("/")
    if any(
        component in {"", ".", ".."} or any(ord(char) < 32 for char in component)
        for component in components
    ):
        raise AcquisitionRejected("ARCHIVE_PATH_INVALID", "ZIP path has unsafe components")
    return unicodedata.normalize("NFC", "/".join(components))


def _check_collisions(parsed: list[tuple[str, zipfile.ZipInfo]]) -> None:
    names: dict[str, str] = {}
    types: dict[str, bool] = {}
    for name, info in parsed:
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            key = unicodedata.normalize("NFC", prefix).casefold()
            old = names.get(key)
            if old is not None and old != prefix:
                raise AcquisitionRejected(
                    "ARCHIVE_COLLISION", "ZIP paths collide after normalization"
                )
            names[key] = prefix
            if index == len(parts):
                if key in types or types.get(key, True) is False:
                    raise AcquisitionRejected("ARCHIVE_COLLISION", "ZIP contains duplicate path")
                types[key] = info.is_dir()
            elif types.get(key) is False:
                raise AcquisitionRejected("ARCHIVE_COLLISION", "ZIP file overlaps a directory")
    for name, info in parsed:
        if info.is_dir():
            continue
        prefix = name + "/"
        if any(other.startswith(prefix) for other, _ in parsed):
            raise AcquisitionRejected("ARCHIVE_COLLISION", "ZIP file overlaps a directory")


def _common_root(parsed: list[tuple[str, zipfile.ZipInfo]]) -> str | None:
    if not parsed:
        return None
    root = parsed[0][0].split("/", 1)[0]
    if any(name != root and not name.startswith(root + "/") for name, _ in parsed):
        return None
    if not any(name.startswith(root + "/") for name, _ in parsed):
        return None
    return root


def _check_path_bounds(path: str, bounds: PoCAcquisitionBounds) -> None:
    if not path or len(path.encode("utf-8")) > bounds.max_path_length:
        raise AcquisitionRejected("ARCHIVE_PATH_INVALID", "ZIP path exceeds bound")
    if len(path.split("/")) > bounds.max_directory_depth:
        raise AcquisitionRejected("ARCHIVE_PATH_INVALID", "ZIP path depth exceeds bound")


def _entry_type(info: zipfile.ZipInfo) -> tuple[Literal["file", "directory"], int | None]:
    mode = info.external_attr >> 16
    if info.create_system == 3:
        kind = stat.S_IFMT(mode)
        if kind == stat.S_IFDIR and info.is_dir():
            return "directory", mode & 0o777
        if kind == stat.S_IFREG and not info.is_dir():
            return "file", mode & 0o777
        raise AcquisitionRejected("ARCHIVE_ENTRY_TYPE_UNSUPPORTED", "ZIP entry type is unsupported")
    if info.create_system == 0:
        if info.is_dir():
            return "directory", None
        if info.external_attr & 0x10:
            raise AcquisitionRejected(
                "ARCHIVE_ENTRY_TYPE_UNSUPPORTED", "ZIP entry type is ambiguous"
            )
        return "file", None
    raise AcquisitionRejected("ARCHIVE_ENTRY_TYPE_UNSUPPORTED", "ZIP creator type is unsupported")
