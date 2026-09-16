"""Logical Artifact storage interface used by capability implementations."""

from pathlib import Path
from typing import Protocol

from boberagent_contracts import ArtifactDescriptor, ArtifactRef, JsonObject


class ArtifactService(Protocol):
    async def create_from_bytes(
        self,
        *,
        artifact_type: str,
        data: bytes,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor: ...

    async def create_from_file(
        self,
        *,
        artifact_type: str,
        path: Path,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor: ...

    async def create_text(
        self,
        *,
        artifact_type: str,
        text: str,
        media_type: str = "text/plain",
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor: ...

    async def get(self, artifact_ref: ArtifactRef) -> ArtifactDescriptor: ...

    async def read_bytes(self, artifact_ref: ArtifactRef) -> bytes: ...
