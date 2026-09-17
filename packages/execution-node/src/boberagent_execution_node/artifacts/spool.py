"""Durable node-local Artifact spool implementing the SDK ArtifactService."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityRunRef,
    JsonObject,
    StorageRef,
)

from boberagent_execution_node.persistence import (
    ArtifactSyncState,
    RuntimeStore,
    SpoolArtifactRecord,
)


class LocalArtifactSpool:
    def __init__(
        self,
        *,
        root: Path,
        allowed_source_roots: tuple[Path, ...],
        store: RuntimeStore,
        run_ref: CapabilityRunRef,
        clock: Callable[[], datetime],
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._allowed_source_roots = tuple(path.resolve() for path in allowed_source_roots)
        self._store = store
        self._run_ref = run_ref
        self._clock = clock

    async def create_from_bytes(
        self,
        *,
        artifact_type: str,
        data: bytes,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor:
        artifact_ref, destination, temporary = self._allocate()
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
            return self._record(
                artifact_ref=artifact_ref,
                destination=destination,
                artifact_type=artifact_type,
                digest=hashlib.sha256(data).hexdigest(),
                size=len(data),
                media_type=media_type,
                metadata=metadata,
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    async def create_from_file(
        self,
        *,
        artifact_type: str,
        path: Path,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor:
        source = path.resolve(strict=True)
        if not source.is_file() or not any(
            source.is_relative_to(root) for root in self._allowed_source_roots
        ):
            raise ValueError("Artifact source must be a file within a managed source root")
        artifact_ref, destination, temporary = self._allocate()
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as source_file, temporary.open("xb") as destination_file:
                while chunk := source_file.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    destination_file.write(chunk)
            os.replace(temporary, destination)
            return self._record(
                artifact_ref=artifact_ref,
                destination=destination,
                artifact_type=artifact_type,
                digest=digest.hexdigest(),
                size=size,
                media_type=media_type,
                metadata=metadata,
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    async def create_text(
        self,
        *,
        artifact_type: str,
        text: str,
        media_type: str = "text/plain",
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor:
        return await self.create_from_bytes(
            artifact_type=artifact_type,
            data=text.encode(),
            media_type=media_type,
            metadata=metadata,
        )

    async def get(self, artifact_ref: ArtifactRef) -> ArtifactDescriptor:
        record = self._store.get_artifact(artifact_ref)
        if record is None:
            raise KeyError(f"unknown local Artifact: {artifact_ref}")
        return record.descriptor

    async def read_bytes(self, artifact_ref: ArtifactRef) -> bytes:
        record = self._store.get_artifact(artifact_ref)
        if record is None:
            raise KeyError(f"unknown local Artifact: {artifact_ref}")
        path = Path(record.local_path).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("persisted Artifact path escapes configured spool root")
        return path.read_bytes()

    def _allocate(self) -> tuple[ArtifactRef, Path, Path]:
        artifact_ref = ArtifactRef(f"artifact-{uuid4()}")
        destination = self._root / f"{artifact_ref}.blob"
        temporary = self._root / f".{artifact_ref}.{uuid4().hex}.tmp"
        return artifact_ref, destination, temporary

    def _record(
        self,
        *,
        artifact_ref: ArtifactRef,
        destination: Path,
        artifact_type: str,
        digest: str,
        size: int,
        media_type: str | None,
        metadata: JsonObject | None,
    ) -> ArtifactDescriptor:
        descriptor = ArtifactDescriptor(
            artifact_id=artifact_ref,
            artifact_type=artifact_type,
            storage_ref=StorageRef(f"node-spool:{artifact_ref}"),
            created_by_run=self._run_ref,
            created_at=self._clock(),
            sha256=digest,
            size_bytes=size,
            media_type=media_type,
            metadata={} if metadata is None else metadata,
        )
        self._store.add_artifact(
            SpoolArtifactRecord(
                descriptor=descriptor,
                local_path=str(destination),
                sync_state=ArtifactSyncState.LOCAL_ONLY,
            )
        )
        return descriptor
