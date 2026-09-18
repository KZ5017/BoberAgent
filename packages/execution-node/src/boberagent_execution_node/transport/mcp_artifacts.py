"""Node-owned Artifact spool adapter for the MCP pull carrier."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import ArtifactDescriptor, ArtifactRef

from boberagent_execution_node.persistence import RuntimeStore


class NodeMcpArtifactSource:
    def __init__(self, *, store: RuntimeStore, spool_root: Path) -> None:
        self._store = store
        self._spool_root = spool_root.resolve()

    async def pending_artifacts(self, limit: int) -> tuple[ArtifactDescriptor, ...]:
        records = self._store.list_artifacts_for_sync()[:limit]
        for record in records:
            self._store.begin_artifact_sync(record.descriptor.artifact_id, datetime.now(UTC))
        return tuple(record.descriptor for record in records)

    async def read_artifact_chunk(
        self, artifact_ref: ArtifactRef, *, offset: int, max_bytes: int
    ) -> bytes:
        record = self._store.get_artifact(artifact_ref)
        if record is None:
            raise KeyError(f"unknown local Artifact: {artifact_ref}")
        path = Path(record.local_path).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(self._spool_root):
            raise ValueError("local Artifact path escapes the configured spool root")
        size = path.stat().st_size
        if offset > size:
            raise ValueError("Artifact offset exceeds local content size")
        with path.open("rb") as stream:
            stream.seek(offset)
            return stream.read(max_bytes)

    async def mark_artifact_synchronized(self, artifact_ref: ArtifactRef) -> None:
        self._store.complete_artifact_sync(artifact_ref)

    async def mark_artifact_failed(self, artifact_ref: ArtifactRef, error: str) -> None:
        self._store.fail_artifact_sync(artifact_ref, error[:1024])
