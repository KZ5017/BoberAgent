"""Immutable Core-owned inspection attempts and byte-grounded evidence identities."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from boberagent_contracts import ArtifactRef, MissionRef, PoCAcquisitionRef
from pydantic import AwareDatetime, Field, model_validator

from boberagent_core.models import CoreModel
from boberagent_core.research.models import PoCCandidateRef, VulnerabilityHypothesisRef

from .classification_models import (
    CLASSIFIER_PROFILE_ID,
    CLASSIFIER_PROFILE_VERSION,
    ClassificationInspectionLimits,
    SupportClassificationDocument,
)
from .evidence_models import InspectionLimits as InspectionLimits
from .evidence_models import SourceCitation as SourceCitation
from .identity import PoCInspectionRef as PoCInspectionRef
from .semantic_models import SemanticInspectionDocument, SemanticInspectionLimits


class InspectionStatus(StrEnum):
    REQUESTED = "REQUESTED"
    INSPECTING = "INSPECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.INTERRUPTED}


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
    limits: InspectionLimits | SemanticInspectionLimits | ClassificationInspectionLimits
    selected_paths: tuple[str, ...] = ()
    status: InspectionStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    document: (
        Annotated[
            InspectionDocument | SemanticInspectionDocument | SupportClassificationDocument,
            Field(discriminator="document_version"),
        ]
        | None
    ) = None
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
            raise ValueError("only COMPLETED inspection carries a validated inspection document")
        if isinstance(self.document, SemanticInspectionDocument):
            limits = self.limits
            if (
                not isinstance(limits, SemanticInspectionLimits)
                or self.profile_id != "m20-c2-deterministic"
                or self.profile_version != "1"
            ):
                raise ValueError("C2 document requires matching semantic profile and limits")
            document = self.document
            bounds = (
                (document.facts, limits.max_facts),
                (document.entrypoint_candidates, limits.max_entrypoint_candidates),
                (document.parameter_candidates, limits.max_parameter_candidates),
                (document.dependency_observations, limits.max_dependency_observations),
                (document.requirements, limits.max_requirements),
                (document.behavior_indicators, limits.max_behavior_indicators),
                (document.risk_indicators, limits.max_risk_indicators),
                (document.unknowns, limits.max_unknowns),
                (document.conflicts, limits.max_conflicts),
                (document.citations, limits.max_citations),
            )
            if any(len(items) > bound for items, bound in bounds):
                raise ValueError("semantic document exceeds persisted limits")
            coverage = {item.path: item for item in document.coverage}
            for citation in document.citations:
                entry = coverage.get(citation.path)
                if (
                    citation.raw_artifact_ref != self.raw_artifact_ref
                    or citation.raw_sha256 != self.raw_sha256
                    or citation.manifest_artifact_ref != self.manifest_artifact_ref
                    or citation.manifest_sha256 != self.manifest_sha256
                    or citation.path not in document.verified_paths
                    or entry is None
                    or citation.entry_sha256 != entry.sha256
                    or entry.size_bytes is None
                    or citation.end > entry.size_bytes
                    or citation.end - citation.start > limits.max_citation_bytes
                ):
                    raise ValueError("semantic citation disagrees with inspection evidence")
        if self.profile_id == CLASSIFIER_PROFILE_ID:
            limits = self.limits
            if not isinstance(limits, ClassificationInspectionLimits) or (
                self.profile_version != CLASSIFIER_PROFILE_VERSION
            ):
                raise ValueError("C3 requires its fixed profile version and typed configuration")
            if self.document is not None and not isinstance(
                self.document, SupportClassificationDocument
            ):
                raise ValueError("C3 requires a classification document")
        if isinstance(self.document, SupportClassificationDocument):
            if self.profile_id != CLASSIFIER_PROFILE_ID or not isinstance(
                self.limits, ClassificationInspectionLimits
            ):
                raise ValueError("classification document requires the C3 profile")
            if (
                self.document.semantic_inspection_ref != self.limits.semantic_inspection_ref
                or self.document.semantic_document_sha256 != self.limits.semantic_document_sha256
            ):
                raise ValueError("classification document disagrees with persisted C2 input")
        return self
