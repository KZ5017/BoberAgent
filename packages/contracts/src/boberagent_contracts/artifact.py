"""Persistent Artifact descriptor."""

from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints

from ._base import ContractModel, JsonObject, SymbolicName
from .refs import ArtifactRef, CapabilityRunRef, StorageRef

type Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ArtifactDescriptor(ContractModel):
    """Logical metadata for persistent evidence or generated non-secret data."""

    artifact_id: ArtifactRef
    artifact_type: SymbolicName
    storage_ref: StorageRef
    created_by_run: CapabilityRunRef
    created_at: AwareDatetime
    sha256: Sha256Digest | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    media_type: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: JsonObject = Field(default_factory=dict)
