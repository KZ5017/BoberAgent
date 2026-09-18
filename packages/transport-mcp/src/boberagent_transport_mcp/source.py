"""Node-owned Artifact source boundary consumed by the MCP server adapter."""

from __future__ import annotations

from typing import Protocol

from boberagent_contracts import ArtifactDescriptor, ArtifactRef


class McpArtifactSource(Protocol):
    async def pending_artifacts(self, limit: int) -> tuple[ArtifactDescriptor, ...]: ...

    async def read_artifact_chunk(
        self, artifact_ref: ArtifactRef, *, offset: int, max_bytes: int
    ) -> bytes: ...

    async def mark_artifact_synchronized(self, artifact_ref: ArtifactRef) -> None: ...

    async def mark_artifact_failed(self, artifact_ref: ArtifactRef, error: str) -> None: ...
