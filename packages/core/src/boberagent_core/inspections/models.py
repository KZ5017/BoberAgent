"""Immutable Core-owned inspection attempts and byte-grounded evidence identities."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from boberagent_contracts import ArtifactRef, MissionRef, PoCAcquisitionRef
from boberagent_contracts.refs import DomainRef
from pydantic import AwareDatetime, Field, model_validator

from boberagent_core.models import CoreModel
from boberagent_core.research.models import PoCCandidateRef, VulnerabilityHypothesisRef


class PoCInspectionRef(DomainRef):
    """Stable identity of one inspection attempt, not a source content hash."""


class InspectionStatus(StrEnum):
    REQUESTED = "REQUESTED"
    INSPECTING = "INSPECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.INTERRUPTED}


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
    """Canonical half-open byte span in a verified decompressed ZIP file."""

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


class InspectionDocument(CoreModel):
    """Versioned structural output only; no semantic source facts in C1."""

    document_version: Literal["m20-c1-evidence-v1"] = "m20-c1-evidence-v1"
    manifest_validated: bool
    zip_reconciled: bool
    verified_paths: tuple[str, ...] = ()
    unverified_paths: tuple[str, ...] = ()
    citations: tuple[SourceCitation, ...] = ()


class PoCInspection(CoreModel):
    inspection_ref: PoCInspectionRef
    mission_ref: MissionRef
    hypothesis_ref: VulnerabilityHypothesisRef
    candidate_ref: PoCCandidateRef
    acquisition_ref: PoCAcquisitionRef
    raw_artifact_ref: ArtifactRef
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_size_bytes: int = Field(ge=0)
    manifest_artifact_ref: ArtifactRef
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolved_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    profile_id: str = Field(min_length=1, max_length=128)
    profile_version: str = Field(min_length=1, max_length=128)
    config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: InspectionLimits
    selected_paths: tuple[str, ...] = ()
    status: InspectionStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    document: InspectionDocument | None = None
    diagnostic: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def lifecycle_shape(self) -> Self:
        if self.status is InspectionStatus.REQUESTED and (
            self.started_at is not None or self.finished_at is not None or self.document is not None
        ):
            raise ValueError("REQUESTED inspection cannot have started or finished output")
        if self.status is InspectionStatus.INSPECTING and (
            self.started_at is None or self.finished_at is not None or self.document is not None
        ):
            raise ValueError("INSPECTING requires start time but no output")
        if self.status.is_terminal and (self.started_at is None or self.finished_at is None):
            raise ValueError("terminal inspection requires start and finish times")
        if (self.status is InspectionStatus.COMPLETED) != (self.document is not None):
            raise ValueError("only COMPLETED inspection carries a validated C1 document")
        return self
