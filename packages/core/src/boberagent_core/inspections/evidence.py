"""Independent read-only validation of retained acquisition evidence.

This module deliberately does not import the Node acquisition inventory producer.
No ZIP member is extracted, imported, compiled, or executed.
"""

from __future__ import annotations

import hashlib
import json
import stat
import struct
import time
import unicodedata
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, BinaryIO, Literal, Self

from boberagent_contracts import ArtifactRef
from pydantic import ConfigDict, Field, StrictBool, StrictInt, ValidationError, model_validator

from boberagent_core.artifacts import CoreArtifactService
from boberagent_core.models import CoreModel

from .models import PoCInspection, SourceCitation

_CHUNK = 64 * 1024
_EOCD = b"PK\x05\x06"


class InspectionError(ValueError):
    """Bounded, source-text-free C1 failure suitable for durable diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ManifestEntry(CoreModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str = Field(min_length=1, max_length=4096)
    type: Literal["file", "directory"]
    mode: StrictInt | None
    executable: StrictBool | None
    size_bytes: StrictInt | None
    sha256: str | None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        _safe_path(self.path)
        if self.mode is not None and not 0 <= self.mode <= 0o777:
            raise ValueError("invalid file mode")
        if self.type == "file":
            if self.size_bytes is None or self.size_bytes < 0 or self.sha256 is None:
                raise ValueError("file requires size and hash")
            _digest(self.sha256)
            if self.executable is not None and (
                self.mode is None or self.executable != bool(self.mode & 0o111)
            ):
                raise ValueError("executable and mode disagree")
        elif self.size_bytes is not None or self.sha256 is not None or self.executable is not None:
            raise ValueError("directory must not declare content")
        return self


class SourceManifest(CoreModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    format_version: Literal["poc-source-manifest-v1"]
    archive_representation: Literal["github_zip"]
    resolved_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    raw_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_archive_size_bytes: StrictInt = Field(ge=0)
    archive_root_prefix: str | None
    entry_count: StrictInt = Field(ge=0)
    total_uncompressed_bytes: StrictInt = Field(ge=0)
    entries: list[ManifestEntry]

    @model_validator(mode="after")
    def structure(self) -> Self:
        if self.archive_root_prefix is not None:
            if not self.archive_root_prefix.endswith("/"):
                raise ValueError("invalid root prefix")
            _safe_path(self.archive_root_prefix[:-1])
            if "/" in self.archive_root_prefix[:-1]:
                raise ValueError("root prefix must be one component")
        paths = tuple(entry.path for entry in self.entries)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("manifest paths must be unique and sorted")
        if len({path.casefold() for path in paths}) != len(paths):
            raise ValueError("manifest paths collide")
        normalized_parents: dict[str, str] = {}
        for position, entry in enumerate(self.entries):
            parts = entry.path.split("/")
            for index in range(1, len(parts) + 1):
                prefix = "/".join(parts[:index])
                key = prefix.casefold()
                previous = normalized_parents.get(key)
                if previous is not None and previous != prefix:
                    raise ValueError("manifest parent paths collide")
                normalized_parents[key] = prefix
            if (
                entry.type == "file"
                and position + 1 < len(paths)
                and paths[position + 1].startswith(entry.path + "/")
            ):
                raise ValueError("manifest file overlaps child path")
        if self.entry_count != len(paths) or self.total_uncompressed_bytes != sum(
            entry.size_bytes or 0 for entry in self.entries
        ):
            raise ValueError("manifest totals disagree")
        return self


def _digest(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("invalid SHA-256")


def _safe_path(value: str) -> None:
    if (
        not value
        or len(value.encode("utf-8")) > 4096
        or unicodedata.normalize("NFC", value) != value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or (len(value) >= 2 and value[1] == ":")
        or any(
            part in {"", ".", ".."} or any(ord(char) < 32 for char in part)
            for part in value.split("/")
        )
    ):
        raise ValueError("unsafe source path")


def _pairs_unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _bounded_hash(stream: IO[bytes], *, maximum: int, deadline: float) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK):
        _deadline(deadline)
        size += len(chunk)
        if size > maximum:
            raise InspectionError("ARTIFACT_SIZE_OVERFLOW")
        digest.update(chunk)
    return digest.hexdigest(), size


def _deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise InspectionError("INSPECTION_LIMIT_EXCEEDED")


def _zip_count(stream: BinaryIO, maximum: int) -> int:
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(max(0, size - 65557))
    tail = stream.read()
    offset = tail.rfind(_EOCD)
    if offset < 0 or len(tail) - offset < 22:
        raise InspectionError("ZIP_INVALID")
    _, disk, central_disk, local_count, count, directory_size, directory_at, comment = (
        struct.unpack_from("<IHHHHIIH", tail, offset)
    )
    if (
        disk != 0
        or central_disk != 0
        or local_count != count
        or count == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_at == 0xFFFFFFFF
        or offset + 22 + comment != len(tail)
        or directory_at + directory_size > size
    ):
        raise InspectionError("ZIP_INVALID")
    if count > maximum + 1:
        raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
    stream.seek(directory_at)
    for _ in range(count):
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise InspectionError("ZIP_INVALID")
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", header, 28)
        raw_name = stream.read(name_size)
        if len(raw_name) != name_size or b"\x00" in raw_name:
            raise InspectionError("ZIP_INVALID")
        stream.seek(extra_size + comment_size, 1)
        if stream.tell() > directory_at + directory_size:
            raise InspectionError("ZIP_INVALID")
    if stream.tell() != directory_at + directory_size:
        raise InspectionError("ZIP_INVALID")
    stream.seek(0)
    return int(count)


def _validate_zip_extra(extra: bytes) -> None:
    """Accept only one fixed GitHub-style UT modification timestamp record."""

    if len(extra) > 1024:
        raise InspectionError("ZIP_INVALID")
    offset = 0
    seen_timestamp = False
    while offset < len(extra):
        if len(extra) - offset < 4:
            raise InspectionError("ZIP_INVALID")
        field_id, length = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if length > len(extra) - offset:
            raise InspectionError("ZIP_INVALID")
        payload = extra[offset : offset + length]
        offset += length
        if field_id != 0x5455 or seen_timestamp or len(payload) != 5 or payload[0] != 0x01:
            raise InspectionError("ZIP_INVALID")
        seen_timestamp = True


def _entry_type(info: zipfile.ZipInfo) -> Literal["file", "directory"]:
    mode = info.external_attr >> 16
    if info.flag_bits & 1 or info.compress_type not in {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
    }:
        raise InspectionError("ZIP_INVALID")
    if info.create_system == 3:
        kind = stat.S_IFMT(mode)
        if kind == stat.S_IFREG and not info.is_dir():
            return "file"
        if kind == stat.S_IFDIR and info.is_dir():
            return "directory"
    elif info.create_system == 0:
        if info.is_dir():
            return "directory"
        if not info.external_attr & 0x10:
            return "file"
    raise InspectionError("ZIP_INVALID")


class VerifiedSource:
    """A reopened, independently revalidated source; no persistent file handles."""

    def __init__(
        self,
        inspection: PoCInspection,
        artifacts: CoreArtifactService,
        *,
        deadline: float,
    ) -> None:
        self.inspection = inspection
        self.artifacts = artifacts
        self.deadline = deadline
        self.manifest = self._validate_artifacts()
        self.entries = {entry.path: entry for entry in self.manifest.entries}
        self._reconcile_zip()

    def _verify_artifact(
        self, artifact_ref: ArtifactRef, expected_hash: str, expected_size: int, label: str
    ) -> None:
        try:
            with self.artifacts.open_content(artifact_ref) as stream:
                actual_hash, actual_size = _bounded_hash(
                    stream, maximum=expected_size, deadline=self.deadline
                )
        except OSError as error:
            raise InspectionError(f"{label}_ARTIFACT_UNAVAILABLE") from error
        except InspectionError as error:
            if error.code == "ARTIFACT_SIZE_OVERFLOW":
                raise InspectionError(f"{label}_SIZE_MISMATCH") from error
            raise
        if actual_size != expected_size:
            raise InspectionError(f"{label}_SIZE_MISMATCH")
        if actual_hash != expected_hash:
            raise InspectionError(f"{label}_HASH_MISMATCH")

    def _validate_artifacts(self) -> SourceManifest:
        inspection = self.inspection
        self._verify_artifact(
            inspection.raw_artifact_ref,
            inspection.raw_sha256,
            inspection.raw_size_bytes,
            "SOURCE",
        )
        record = self.artifacts.get(inspection.manifest_artifact_ref)
        if record is None or record.descriptor.size_bytes is None:
            raise InspectionError("MANIFEST_ARTIFACT_UNAVAILABLE")
        size = record.descriptor.size_bytes
        if size > inspection.limits.max_manifest_bytes:
            raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
        self._verify_artifact(
            inspection.manifest_artifact_ref, inspection.manifest_sha256, size, "MANIFEST"
        )
        try:
            with self.artifacts.open_content(inspection.manifest_artifact_ref) as stream:
                payload = stream.read(inspection.limits.max_manifest_bytes + 1)
            if len(payload) > inspection.limits.max_manifest_bytes:
                raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
            decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs_unique)
            manifest = SourceManifest.model_validate(decoded, strict=True)
        except (ValueError, UnicodeError, ValidationError, RecursionError) as error:
            raise InspectionError("MANIFEST_INVALID") from error
        if (
            manifest.raw_archive_sha256 != inspection.raw_sha256
            or manifest.raw_archive_size_bytes != inspection.raw_size_bytes
            or manifest.resolved_commit_sha != inspection.resolved_commit_sha
            or manifest.archive_representation != "github_zip"
        ):
            raise InspectionError("MANIFEST_IDENTITY_MISMATCH")
        if manifest.entry_count > inspection.limits.max_zip_entries:
            raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
        return manifest

    @contextmanager
    def _archive(self) -> Iterator[zipfile.ZipFile]:
        try:
            with self.artifacts.open_content(self.inspection.raw_artifact_ref) as stream:
                expected_entries = _zip_count(stream, self.inspection.limits.max_zip_entries)
                with zipfile.ZipFile(stream, "r") as archive:
                    if len(archive.infolist()) != expected_entries:
                        raise InspectionError("ZIP_INVALID")
                    yield archive
        except (
            zipfile.BadZipFile,
            EOFError,
            OSError,
            RuntimeError,
            NotImplementedError,
            zlib.error,
        ) as error:
            raise InspectionError("ZIP_INVALID") from error

    def _reconcile_zip(self) -> None:
        with self._archive() as archive:
            infos = archive.infolist()
            if len(infos) > self.inspection.limits.max_zip_entries + 1:
                raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
            parsed: list[tuple[str, zipfile.ZipInfo]] = []
            seen: set[str] = set()
            for info in infos:
                _deadline(self.deadline)
                _validate_zip_extra(info.extra)
                try:
                    name = info.filename.rstrip("/")
                    _safe_path(name)
                except ValueError as error:
                    raise InspectionError("ZIP_INVALID") from error
                folded = name.casefold()
                if folded in seen:
                    raise InspectionError("ZIP_INVALID")
                seen.add(folded)
                parsed.append((name, info))
            root = parsed[0][0].split("/", 1)[0] if parsed else None
            common = (
                root is not None
                and all(name == root or name.startswith(root + "/") for name, _ in parsed)
                and any(name.startswith(root + "/") for name, _ in parsed)
            )
            prefix = f"{root}/" if common else None
            if prefix != self.manifest.archive_root_prefix:
                raise InspectionError("ZIP_MANIFEST_MISMATCH")
            actual: dict[str, zipfile.ZipInfo] = {}
            for name, info in parsed:
                if prefix is not None and name == root and info.is_dir():
                    continue
                relative = name[len(prefix) :] if prefix is not None else name
                if relative in actual:
                    raise InspectionError("ZIP_MANIFEST_MISMATCH")
                actual[relative] = info
            if set(actual) != set(self.entries):
                raise InspectionError("ZIP_MANIFEST_MISMATCH")
            for path, info in actual.items():
                entry = self.entries[path]
                if _entry_type(info) != entry.type:
                    raise InspectionError("ZIP_MANIFEST_MISMATCH")
                mode = (info.external_attr >> 16) & 0o777 if info.create_system == 3 else None
                executable = (
                    None if mode is None or entry.type == "directory" else bool(mode & 0o111)
                )
                if entry.mode != mode or entry.executable != executable:
                    raise InspectionError("ZIP_MANIFEST_MISMATCH")
                if entry.type == "directory":
                    if info.file_size != 0:
                        raise InspectionError("ZIP_MANIFEST_MISMATCH")
                elif info.file_size != entry.size_bytes:
                    raise InspectionError("ENTRY_SIZE_MISMATCH")

    def verify_entry(self, path: str) -> bytes:
        """Return one bounded, hash-verified entry for citation construction."""

        entry = self.entries.get(path)
        if entry is None or entry.type != "file" or entry.size_bytes is None:
            raise InspectionError("ZIP_MANIFEST_MISMATCH")
        if entry.size_bytes > self.inspection.limits.max_entry_bytes:
            raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
        name = (self.manifest.archive_root_prefix or "") + path
        with self._archive() as archive:
            digest = hashlib.sha256()
            content = bytearray()
            try:
                with archive.open(name) as stream:
                    while chunk := stream.read(_CHUNK):
                        _deadline(self.deadline)
                        content.extend(chunk)
                        if len(content) > self.inspection.limits.max_entry_bytes:
                            raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
                        digest.update(chunk)
            except (
                KeyError,
                zipfile.BadZipFile,
                EOFError,
                OSError,
                RuntimeError,
                zlib.error,
            ) as error:
                raise InspectionError("ZIP_INVALID") from error
            if len(content) != entry.size_bytes:
                raise InspectionError("ENTRY_SIZE_MISMATCH")
            if digest.hexdigest() != entry.sha256:
                raise InspectionError("ENTRY_HASH_MISMATCH")
            return bytes(content)

    def validate_citation(self, citation: SourceCitation, content: bytes) -> None:
        inspection = self.inspection
        entry = self.entries.get(citation.path)
        if (
            citation.raw_artifact_ref != inspection.raw_artifact_ref
            or citation.raw_sha256 != inspection.raw_sha256
            or citation.manifest_artifact_ref != inspection.manifest_artifact_ref
            or citation.manifest_sha256 != inspection.manifest_sha256
            or entry is None
            or entry.type != "file"
            or citation.entry_sha256 != entry.sha256
            or citation.end > len(content)
            or citation.end - citation.start > inspection.limits.max_citation_bytes
        ):
            raise InspectionError("CITATION_INVALID")


def line_span(content: bytes, start: int, end: int) -> tuple[int, int] | None:
    """Return 1-based inclusive display lines, or None for undecodable bytes.

    Canonical citations remain byte offsets. CRLF counts as one newline, as does LF.
    """

    if start < 0 or end <= start or end > len(content):
        raise ValueError("invalid byte span")
    if content.startswith(b"\xff\xfe"):
        encoding = "utf-16-le"
        bom = 2
    elif content.startswith(b"\xfe\xff"):
        encoding = "utf-16-be"
        bom = 2
    elif content.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8"
        bom = 3
    else:
        encoding = "utf-8"
        bom = 0
    try:
        decoded = content[bom:].decode(encoding, errors="strict")
        if any((ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127 for char in decoded):
            return None
        prefix = content[bom:start].decode(encoding, errors="strict")
        through = content[bom:end].decode(encoding, errors="strict")
    except UnicodeError:
        return None
    return prefix.count("\n") + 1, through.rstrip("\r\n").count("\n") + 1
