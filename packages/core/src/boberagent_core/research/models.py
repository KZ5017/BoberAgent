"""Core-owned, bounded M20-A research records; none imply target vulnerability."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from boberagent_contracts import AssetRef, MissionRef, ObservationRef, ServiceRef
from boberagent_contracts.refs import DomainRef
from pydantic import AwareDatetime, Field, model_validator

from boberagent_core.models import CoreModel


class VulnerabilityHypothesisRef(DomainRef):
    """Stable Core-owned identity for one bounded claim about one Asset."""


class PoCCandidateRef(DomainRef):
    """Stable logical research-lead identity, independent of a source URL."""


class ResearchAttemptRef(DomainRef):
    """Stable identity for one provider request and its durable outcome."""


class HypothesisStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ResearchStatus(StrEnum):
    STARTED = "STARTED"
    INTERRUPTED = "INTERRUPTED"
    FOUND = "FOUND"
    NO_MATCH = "NO_MATCH"
    PARTIAL = "PARTIAL"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class ResearchResponseStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class SourceClass(StrEnum):
    REPOSITORY = "repository"
    ADVISORY = "advisory"
    PUBLICATION = "publication"
    OTHER = "other"


class HitDecision(StrEnum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


class VulnerabilityHypothesis(CoreModel):
    hypothesis_ref: VulnerabilityHypothesisRef
    mission_ref: MissionRef
    asset_ref: AssetRef
    service_ref: ServiceRef | None = None
    claim: str = Field(min_length=8, max_length=512)
    vulnerability_ids: tuple[str, ...] = Field(default=(), max_length=16)
    product: str | None = Field(default=None, min_length=1, max_length=128)
    version: str | None = Field(default=None, min_length=1, max_length=128)
    supporting_observation_refs: tuple[ObservationRef, ...] = Field(default=(), max_length=32)
    provenance: str = Field(min_length=1, max_length=255)
    status: HypothesisStatus = HypothesisStatus.ACTIVE
    created_at: AwareDatetime

    @model_validator(mode="after")
    def unique_support(self) -> Self:
        if len(self.supporting_observation_refs) != len(set(self.supporting_observation_refs)):
            raise ValueError("supporting ObservationRefs must be unique")
        if len(self.vulnerability_ids) != len(set(self.vulnerability_ids)):
            raise ValueError("vulnerability identifiers must be unique")
        if any(not value.strip() or len(value) > 64 for value in self.vulnerability_ids):
            raise ValueError("vulnerability identifiers must be nonempty and bounded")
        return self


class ResearchRequest(CoreModel):
    hypothesis_ref: VulnerabilityHypothesisRef
    mission_ref: MissionRef
    asset_ref: AssetRef
    service_ref: ServiceRef | None = None
    query_terms: tuple[str, ...] = Field(min_length=1, max_length=20)
    vulnerability_ids: tuple[str, ...] = Field(default=(), max_length=16)
    allowed_source_classes: tuple[SourceClass, ...] = Field(min_length=1, max_length=4)
    result_limit: int = Field(ge=1, le=50)
    published_after: AwareDatetime | None = None
    published_before: AwareDatetime | None = None

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if any(not term.strip() or len(term) > 512 for term in self.query_terms):
            raise ValueError("research query terms must be nonempty and bounded")
        if len(set(self.allowed_source_classes)) != len(self.allowed_source_classes):
            raise ValueError("allowed source classes must be unique")
        if (
            self.published_after
            and self.published_before
            and self.published_after > self.published_before
        ):
            raise ValueError("research date range is reversed")
        return self


class SourceHit(CoreModel):
    """Untrusted provider claim, preserved as data rather than an instruction."""

    source_class: SourceClass
    source_uri: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    summary: str | None = Field(default=None, max_length=2048)
    match_excerpt: str | None = Field(default=None, max_length=1024)
    vulnerability_ids: tuple[str, ...] = Field(default=(), max_length=16)
    claimed_product: str | None = Field(default=None, max_length=128)
    claimed_version: str | None = Field(default=None, max_length=128)
    repository_identity: str | None = Field(default=None, max_length=2048)
    revision_claim: str | None = Field(default=None, max_length=255)
    language_hint: str | None = Field(default=None, max_length=64)
    runtime_hint: str | None = Field(default=None, max_length=128)
    published_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    provider_result_id: str | None = Field(default=None, max_length=255)


class ResearchResult(CoreModel):
    status: ResearchResponseStatus
    hits: tuple[SourceHit, ...] = Field(default=(), max_length=50)
    diagnostic: str | None = Field(default=None, max_length=512)


class ResearchAttempt(CoreModel):
    attempt_ref: ResearchAttemptRef
    hypothesis_ref: VulnerabilityHypothesisRef
    provider_id: str = Field(min_length=1, max_length=128)
    request: ResearchRequest
    status: ResearchStatus
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    diagnostic: str | None = Field(default=None, max_length=512)


class PoCCandidate(CoreModel):
    candidate_ref: PoCCandidateRef
    mission_ref: MissionRef
    hypothesis_ref: VulnerabilityHypothesisRef
    source_identity: str = Field(min_length=1, max_length=2048)
    source_class: SourceClass
    source_uri: str = Field(min_length=1, max_length=2048)
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime


class ResearchSourceHit(CoreModel):
    hit_id: int
    attempt_ref: ResearchAttemptRef
    candidate_ref: PoCCandidateRef | None = None
    provider_id: str
    source: SourceHit
    source_identity: str | None = None
    decision: HitDecision
    decision_reason: str | None = None
    observed_at: AwareDatetime
