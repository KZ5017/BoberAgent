"""Bounded exact ZIP-to-manifest reconciliation; never executes acquired source."""

from __future__ import annotations

import hashlib
import os
import stat
import struct
import time
import unicodedata
import zipfile
import zlib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from boberagent_contracts import PreparationBudgets, Sha256Digest
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class MaterializationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    type: Literal["file", "directory"]
    mode: int | None
    executable: bool | None
    size_bytes: int | None
    sha256: Sha256Digest | None


class StructuralManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal["poc-source-manifest-v1"]
    archive_representation: Literal["github_zip"]
    resolved_commit_sha: str
    raw_archive_sha256: Sha256Digest
    raw_archive_size_bytes: int = Field(ge=0)
    archive_root_prefix: str | None
    entry_count: int = Field(ge=0)
    total_uncompressed_bytes: int = Field(ge=0)
    entries: tuple[ManifestEntry, ...]

    @model_validator(mode="after")
    def consistent(self) -> StructuralManifest:
        if self.entry_count != len(self.entries) or self.entries != tuple(
            sorted(self.entries, key=lambda entry: entry.path)
        ):
            raise ValueError("manifest entries are not canonical")
        if self.total_uncompressed_bytes != sum(
            entry.size_bytes or 0 for entry in self.entries if entry.type == "file"
        ):
            raise ValueError("manifest byte total disagrees")
        for entry in self.entries:
            if entry.mode is not None and not 0 <= entry.mode <= 0o777:
                raise ValueError("manifest file mode is invalid")
            if (
                entry.executable is not None
                and entry.mode is not None
                and (entry.executable != bool(entry.mode & 0o111))
            ):
                raise ValueError("manifest executable flag disagrees with mode")
            if entry.type == "file" and (entry.sha256 is None or entry.size_bytes is None):
                raise ValueError("manifest file lacks identity")
            if entry.type == "directory" and (
                entry.sha256 is not None or entry.size_bytes is not None
            ):
                raise ValueError("manifest directory has content identity")
        return self


@dataclass(frozen=True)
class MaterializedTree:
    file_count: int
    byte_count: int
    tree_sha256: str


_CHUNK = 64 * 1024
_END = b"PK\x05\x06"


def _safe_name(raw: str, maximum_depth: int) -> str:
    if (
        not raw
        or "\x00" in raw
        or "\\" in raw
        or raw.startswith("/")
        or raw.endswith("//")
        or (len(raw) >= 2 and raw[1] == ":")
    ):
        raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
    parts = raw.rstrip("/").split("/")
    if len(parts) > maximum_depth or any(
        part in {"", ".", ".."} or any(ord(char) < 32 for char in part) for part in parts
    ):
        raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
    normalized = unicodedata.normalize("NFC", "/".join(parts))
    return normalized


def _check_collisions(paths: list[tuple[str, bool]]) -> None:
    seen: dict[str, tuple[str, bool]] = {}
    for path, directory in paths:
        key = path.casefold()
        if key in seen:
            raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
        seen[key] = path, directory
    canonical: dict[str, str] = {}
    for path, _directory in paths:
        parts = path.split("/")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            key = prefix.casefold()
            previous = canonical.setdefault(key, prefix)
            if previous != prefix:
                raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
            if index < len(parts) and key in seen and not seen[key][1]:
                raise MaterializationError("SOURCE_INTEGRITY_FAILURE")


def _preflight_zip(path: Path, max_count: int) -> None:
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read()
    offset = tail.rfind(_END)
    if offset < 0 or len(tail) - offset < 22:
        raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
    (_, disk, central_disk, disk_count, count, directory_size, directory_at, comment) = (
        struct.unpack_from("<IHHHHIIH", tail, offset)
    )
    if (
        disk != 0
        or central_disk != 0
        or disk_count != count
        or count == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_at == 0xFFFFFFFF
        or offset + 22 + comment != len(tail)
        or directory_at + directory_size > size
        or count > max_count + 1  # GitHub's archive root may have a directory marker.
    ):
        raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
    with path.open("rb") as stream:
        stream.seek(directory_at)
        for _ in range(count):
            header = stream.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
            name_size, extra_size, comment_size = struct.unpack_from("<HHH", header, 28)
            name = stream.read(name_size)
            if len(name) != name_size or b"\x00" in name:
                raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
            stream.seek(extra_size + comment_size, os.SEEK_CUR)
            if stream.tell() > directory_at + directory_size:
                raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
        if stream.tell() != directory_at + directory_size:
            raise MaterializationError("SOURCE_INTEGRITY_FAILURE")


def _validate_extra(extra: bytes) -> None:
    if len(extra) > 1024:
        raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
    cursor = 0
    seen = False
    while cursor < len(extra):
        if len(extra) - cursor < 4:
            raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
        field, size = struct.unpack_from("<HH", extra, cursor)
        cursor += 4
        if size > len(extra) - cursor:
            raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
        value = extra[cursor : cursor + size]
        cursor += size
        if field != 0x5455 or seen or len(value) != 5 or value[0] != 1:
            raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
        seen = True


def _entry_kind(info: zipfile.ZipInfo) -> tuple[str, int | None]:
    mode = info.external_attr >> 16
    if info.create_system == 3:
        kind = stat.S_IFMT(mode)
        if kind == stat.S_IFDIR and info.is_dir():
            return "directory", mode & 0o777
        if kind == stat.S_IFREG and not info.is_dir():
            return "file", mode & 0o777
    elif info.create_system == 0:
        if info.is_dir():
            return "directory", None
        if not info.external_attr & 0x10:
            return "file", None
    raise MaterializationError("SOURCE_INTEGRITY_FAILURE")


def _directory_fd(parent: int, name: str) -> int:
    with suppress(FileExistsError):
        os.mkdir(name, mode=0o700, dir_fd=parent)
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _write_member(
    root_fd: int,
    relative: str,
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    entry: ManifestEntry,
    budgets: PreparationBudgets,
    deadline: float,
    current_total: int,
    imported_bytes: int,
) -> int:
    parts = relative.split("/")
    parent = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            next_fd = _directory_fd(parent, component)
            os.close(parent)
            parent = next_fd
        if entry.type == "directory":
            directory_fd = _directory_fd(parent, parts[-1])
            os.close(directory_fd)
            return 0
        output = os.open(
            parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        size = 0
        digest = hashlib.sha256()
        try:
            with archive.open(info) as source:
                while chunk := source.read(_CHUNK):
                    size += len(chunk)
                    if (
                        time.monotonic() > deadline
                        or size > (entry.size_bytes or 0)
                        or current_total + size > budgets.max_materialized_bytes
                        or current_total + size > budgets.max_preparation_write_bytes
                        or imported_bytes + current_total + size > budgets.max_temporary_bytes
                    ):
                        raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
                    digest.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        view = view[os.write(output, view) :]
            os.fsync(output)
        finally:
            os.close(output)
        if size != entry.size_bytes or digest.hexdigest() != entry.sha256:
            raise MaterializationError("MANIFEST_MISMATCH")
        return size
    finally:
        os.close(parent)


def parse_manifest(
    data: bytes, raw_hash: str, raw_size: int, commit: str, budgets: PreparationBudgets
) -> StructuralManifest:
    try:
        manifest = StructuralManifest.model_validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MaterializationError("MANIFEST_MISMATCH") from error
    if (
        manifest.raw_archive_sha256 != raw_hash
        or manifest.raw_archive_size_bytes != raw_size
        or manifest.resolved_commit_sha != commit
        or manifest.entry_count > budgets.max_file_count
        or manifest.total_uncompressed_bytes > budgets.max_materialized_bytes
    ):
        raise MaterializationError("MANIFEST_MISMATCH")
    paths = []
    for entry in manifest.entries:
        canonical = _safe_name(entry.path, budgets.max_path_depth)
        if canonical != entry.path:
            raise MaterializationError("MANIFEST_MISMATCH")
        paths.append((canonical, entry.type == "directory"))
    _check_collisions(paths)
    if manifest.archive_root_prefix is not None:
        prefix = manifest.archive_root_prefix
        if not prefix.endswith("/") or "/" in prefix[:-1]:
            raise MaterializationError("MANIFEST_MISMATCH")
        if _safe_name(prefix, budgets.max_path_depth) != prefix[:-1]:
            raise MaterializationError("MANIFEST_MISMATCH")
    return manifest


def materialize_zip(
    archive_path: Path,
    manifest: StructuralManifest,
    staging: Path,
    budgets: PreparationBudgets,
    *,
    started: float,
    imported_bytes: int = 0,
) -> MaterializedTree:
    """Stream each exact regular member under a no-follow directory fd."""
    if archive_path.stat().st_size > budgets.max_imported_artifact_bytes:
        raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
    if imported_bytes + manifest.total_uncompressed_bytes > budgets.max_temporary_bytes:
        raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
    _preflight_zip(archive_path, budgets.max_file_count)
    expected = {entry.path: entry for entry in manifest.entries}
    observed: set[str] = set()
    total = 0
    files = 0
    deadline = started + budgets.max_total_runtime_seconds
    root_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > budgets.max_file_count + 1:
                raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
            raw_paths = [
                (_safe_name(info.filename, budgets.max_path_depth + 1), info.is_dir())
                for info in infos
            ]
            _check_collisions(raw_paths)
            for info in infos:
                if time.monotonic() > deadline:
                    raise MaterializationError("PREPARATION_TIMEOUT")
                _validate_extra(info.extra)
                if info.flag_bits & 1 or info.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
                kind, mode = _entry_kind(info)
                name = _safe_name(info.filename, budgets.max_path_depth + 1)
                prefix = manifest.archive_root_prefix
                if prefix is not None:
                    root = prefix[:-1]
                    if name == root and kind == "directory":
                        continue
                    if not name.startswith(prefix):
                        raise MaterializationError("MANIFEST_MISMATCH")
                    name = name[len(prefix) :]
                name = _safe_name(name, budgets.max_path_depth)
                entry = expected.get(name)
                if entry is None or name in observed or entry.type != kind or entry.mode != mode:
                    raise MaterializationError("MANIFEST_MISMATCH")
                if kind == "directory" and info.file_size != 0:
                    raise MaterializationError("SOURCE_INTEGRITY_FAILURE")
                if kind == "file" and info.file_size != entry.size_bytes:
                    raise MaterializationError("MANIFEST_MISMATCH")
                if kind == "file" and (
                    info.file_size > budgets.max_materialized_bytes - total
                    or imported_bytes + info.file_size > budgets.max_temporary_bytes - total
                    or info.file_size > 10_000 * max(info.compress_size, 1)
                ):
                    raise MaterializationError("WORKSPACE_LIMIT_EXCEEDED")
                written = _write_member(
                    root_fd,
                    name,
                    archive,
                    info,
                    entry,
                    budgets,
                    deadline,
                    total,
                    imported_bytes,
                )
                total += written
                files += kind == "file"
                observed.add(name)
            if observed != expected.keys() or total != manifest.total_uncompressed_bytes:
                raise MaterializationError("MANIFEST_MISMATCH")
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError, zlib.error) as error:
        raise MaterializationError("SOURCE_INTEGRITY_FAILURE") from error
    finally:
        os.close(root_fd)
    # Apply read-only modes only after the entire manifest has reconciled.
    for directory, directories, filenames in os.walk(staging, topdown=False, followlinks=False):
        for filename in filenames:
            path = Path(directory) / filename
            if path.is_symlink() or not path.is_file():
                raise MaterializationError("PREPARED_CONTENT_MISMATCH")
            path.chmod(0o444)
        for name in directories:
            path = Path(directory) / name
            if path.is_symlink():
                raise MaterializationError("PREPARED_CONTENT_MISMATCH")
            path.chmod(0o555)
    # Keep the staging directory writable for the atomic rename. The published
    # root is made read-only at the publication boundary by the owner service.
    tree_digest = hashlib.sha256(
        "".join(
            f"{item.path}\0{item.type}\0{item.size_bytes}\0{item.sha256}\n"
            for item in manifest.entries
        ).encode()
    ).hexdigest()
    return MaterializedTree(files, total, tree_digest)


def verify_published(path: Path, manifest: StructuralManifest, expected: MaterializedTree) -> None:
    """Re-read every published file; directory existence alone proves nothing."""
    if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o222:
        raise MaterializationError("PREPARED_CONTENT_MISMATCH")
    expected_files = {entry.path: entry for entry in manifest.entries if entry.type == "file"}
    expected_directories = {entry.path for entry in manifest.entries if entry.type == "directory"}
    for entry in manifest.entries:
        parts = entry.path.split("/")
        expected_directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for directory, directories, files in os.walk(path, followlinks=False):
        relative = Path(directory).relative_to(path)
        for name in directories:
            member = Path(directory) / name
            if member.is_symlink() or member.stat().st_mode & 0o222:
                raise MaterializationError("PREPARED_CONTENT_MISMATCH")
            actual_directories.add((relative / name).as_posix())
        for name in files:
            member = Path(directory) / name
            if member.is_symlink() or not member.is_file() or member.stat().st_mode & 0o222:
                raise MaterializationError("PREPARED_CONTENT_MISMATCH")
            identity = (relative / name).as_posix()
            file_entry = expected_files.get(identity)
            if file_entry is None:
                raise MaterializationError("PREPARED_CONTENT_MISMATCH")
            digest = hashlib.sha256()
            count = 0
            with member.open("rb") as stream:
                for chunk in iter(lambda: stream.read(_CHUNK), b""):
                    count += len(chunk)
                    digest.update(chunk)
            if count != file_entry.size_bytes or digest.hexdigest() != file_entry.sha256:
                raise MaterializationError("PREPARED_CONTENT_MISMATCH")
            actual_files.add(identity)
    tree_digest = hashlib.sha256(
        "".join(
            f"{item.path}\0{item.type}\0{item.size_bytes}\0{item.sha256}\n"
            for item in manifest.entries
        ).encode()
    ).hexdigest()
    if (
        actual_files != expected_files.keys()
        or actual_directories != expected_directories
        or len(actual_files) != expected.file_count
        or sum(item.size_bytes or 0 for item in expected_files.values()) != expected.byte_count
        or tree_digest != expected.tree_sha256
    ):
        raise MaterializationError("PREPARED_CONTENT_MISMATCH")
