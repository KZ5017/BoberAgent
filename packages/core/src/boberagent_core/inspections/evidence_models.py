"""Shared evidence identities for versioned C1 and C2 documents."""

from typing import Self

from boberagent_contracts import ArtifactRef
from pydantic import Field, model_validator

from boberagent_core.models import CoreModel


class InspectionLimits(CoreModel):
    """C1 verification limits, deliberately independent of acquisition bounds."""

    max_manifest_bytes: int = Field(default=16 * 1024 * 1024, ge=1)
    max_zip_entries: int = Field(default=10_000, ge=1)
    max_entry_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    max_total_verified_bytes: int = Field(default=512 * 1024 * 1024, ge=1)
    max_citation_bytes: int = Field(default=64 * 1024, ge=1)
    max_citations: int = Field(default=100, ge=1)
    max_wall_seconds: float = Field(default=30.0, gt=0)


class SourceCitation(CoreModel):
    """Canonical nonempty half-open span in a verified decompressed entry."""

    raw_artifact_ref: ArtifactRef
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_artifact_ref: ArtifactRef
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str = Field(min_length=1, max_length=4096)
    entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    reader_id: str = Field(min_length=1, max_length=128)
    reader_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def nonempty_ordered_span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("source citation must have a nonempty ordered byte span")
        return self
