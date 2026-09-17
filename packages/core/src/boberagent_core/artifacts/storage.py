"""Core-owned, confined filesystem content storage for verified Artifacts."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArtifactStorageError(ValueError):
    """A transfer cannot be safely represented in managed storage."""


class ArtifactOffsetError(ArtifactStorageError):
    """A chunk is missing, out of order, or conflicts with durable bytes."""


class ArtifactIntegrityError(ArtifactStorageError):
    """Received bytes do not match declared content metadata."""


class ArtifactStorageConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    root: Path
    max_artifact_size_bytes: int = Field(default=16 * 1024**3, ge=0)
    max_chunk_size_bytes: int = Field(default=1024 * 1024, ge=1, le=1024 * 1024)

    @field_validator("root", mode="before")
    @classmethod
    def expand_root(cls, value: object) -> object:
        return value.expanduser() if isinstance(value, Path) else value


class FilesystemArtifactStorage:
    """Content-addressed bytes with deterministic, non-domain physical keys."""

    def __init__(self, configuration: ArtifactStorageConfiguration) -> None:
        self.configuration = configuration
        self._root = configuration.root.resolve()
        self._content_root = self._root / "content"
        self._incoming_root = self._root / "incoming"
        self._content_root.mkdir(parents=True, exist_ok=True)
        self._incoming_root.mkdir(parents=True, exist_ok=True)

    def reconcile_transfer(self, transfer_id: str, persisted_offset: int) -> int:
        path = self._temporary_path(transfer_id)
        if not path.exists():
            path.touch(exist_ok=False)
            return 0
        actual = path.stat().st_size
        if actual < persisted_offset:
            with path.open("wb"):
                pass
            return 0
        if actual > persisted_offset:
            with path.open("r+b") as stream:
                stream.truncate(persisted_offset)
            return persisted_offset
        return actual

    def append_chunk(
        self,
        transfer_id: str,
        *,
        offset: int,
        data: bytes,
        durable_offset: int,
        declared_size: int,
    ) -> int:
        if len(data) > self.configuration.max_chunk_size_bytes:
            raise ArtifactStorageError("Artifact chunk exceeds the configured maximum")
        if offset + len(data) > declared_size:
            raise ArtifactOffsetError("Artifact chunk exceeds the declared size")
        path = self._temporary_path(transfer_id)
        if offset < durable_offset:
            if offset + len(data) > durable_offset:
                raise ArtifactOffsetError("Artifact chunk overlaps undelivered content")
            with path.open("rb") as stream:
                stream.seek(offset)
                if stream.read(len(data)) != data:
                    raise ArtifactOffsetError(
                        "duplicate Artifact chunk conflicts with stored bytes"
                    )
            return durable_offset
        if offset > durable_offset:
            raise ArtifactOffsetError("Artifact chunk offset leaves a missing range")
        with path.open("r+b") as stream:
            stream.seek(offset)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return offset + len(data)

    def verify_temporary(self, transfer_id: str, *, digest: str, size: int) -> None:
        path = self._temporary_path(transfer_id)
        actual_digest, actual_size = _hash_file(path)
        if actual_size != size:
            raise ArtifactIntegrityError(
                f"Artifact size mismatch: declared {size}, received {actual_size}"
            )
        if actual_digest != digest:
            raise ArtifactIntegrityError("Artifact SHA-256 does not match received bytes")

    def publish(self, transfer_id: str, *, digest: str, size: int) -> tuple[str, bool]:
        temporary = self._temporary_path(transfer_id)
        content_key = f"sha256/{digest[:2]}/{digest}.blob"
        destination = self._content_path(content_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        deduplicated = destination.exists()
        if deduplicated:
            existing_digest, existing_size = _hash_file(destination)
            if existing_digest != digest or existing_size != size:
                raise ArtifactIntegrityError("content-addressed Artifact collision detected")
            temporary.unlink(missing_ok=True)
        else:
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            _fsync_directory(destination.parent)
        return content_key, deduplicated

    def discard_transfer(self, transfer_id: str) -> None:
        self._temporary_path(transfer_id).unlink(missing_ok=True)

    def content_exists(self, content_key: str) -> bool:
        return self._content_path(content_key).is_file()

    @contextmanager
    def open_content(self, content_key: str) -> Iterator[BinaryIO]:
        with self._content_path(content_key).open("rb") as stream:
            yield stream

    def read_content(self, content_key: str) -> bytes:
        with self.open_content(content_key) as stream:
            return stream.read()

    def _temporary_path(self, transfer_id: str) -> Path:
        safe_name = hashlib.sha256(transfer_id.encode("utf-8")).hexdigest()
        return self._incoming_root / f"{safe_name}.part"

    def _content_path(self, content_key: str) -> Path:
        relative = PurePosixPath(content_key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ArtifactStorageError("Artifact content key is not confined")
        path = (self._content_root / Path(*relative.parts)).resolve()
        if not path.is_relative_to(self._content_root):
            raise ArtifactStorageError("Artifact content path escapes managed storage")
        return path


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
