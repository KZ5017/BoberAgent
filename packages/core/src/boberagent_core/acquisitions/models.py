"""Core-owned M20-B acquisition decision and durable lifecycle snapshots."""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from boberagent_contracts import CapabilityRunRef, MissionRef, PoCAcquisitionRef
from boberagent_contracts.poc_acquisition import (
    PoCAcquisitionBounds,
    PoCSourceAcquisitionReceipt,
)
from pydantic import AwareDatetime, Field, model_validator

from boberagent_core.models import CoreModel
from boberagent_core.research.models import (
    PoCCandidateRef,
    ResearchAttemptRef,
    VulnerabilityHypothesisRef,
)


class PoCAcquisitionStatus(StrEnum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    AWAITING_ARTIFACT = "AWAITING_ARTIFACT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            PoCAcquisitionStatus.COMPLETED,
            PoCAcquisitionStatus.FAILED,
            PoCAcquisitionStatus.REJECTED,
            PoCAcquisitionStatus.INTERRUPTED,
        }


class PoCAcquisition(CoreModel):
    """One explicit attempt, separate from its candidate, Run, and immutable bytes."""

    acquisition_ref: PoCAcquisitionRef
    mission_ref: MissionRef
    hypothesis_ref: VulnerabilityHypothesisRef
    candidate_ref: PoCCandidateRef
    selected_hit_id: int = Field(ge=1)
    research_attempt_ref: ResearchAttemptRef
    research_provider_id: str = Field(min_length=1, max_length=128)
    source_identity: str = Field(min_length=1, max_length=2048)
    source_uri: str = Field(min_length=1, max_length=2048)
    repository_uri: str = Field(min_length=1, max_length=255)
    provider_repository_id: int = Field(ge=1)
    historical_ref: str = Field(min_length=8, max_length=247)
    bounds: PoCAcquisitionBounds
    status: PoCAcquisitionStatus
    run_ref: CapabilityRunRef | None = None
    routing_provider_id: UUID | None = None
    node_id: str | None = Field(default=None, min_length=1, max_length=255)
    receipt: PoCSourceAcquisitionReceipt | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    diagnostic: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def lifecycle_fields(self) -> Self:
        if self.status is PoCAcquisitionStatus.REQUESTED and (
            self.run_ref is not None or self.receipt is not None
        ):
            raise ValueError("REQUESTED acquisition cannot have a Run or receipt")
        if self.status in {
            PoCAcquisitionStatus.DISPATCHED,
            PoCAcquisitionStatus.AWAITING_ARTIFACT,
            PoCAcquisitionStatus.COMPLETED,
        } and (self.run_ref is None or self.routing_provider_id is None or self.node_id is None):
            raise ValueError("dispatched acquisition requires Run and provider routing")
        if (
            self.status
            in {
                PoCAcquisitionStatus.AWAITING_ARTIFACT,
                PoCAcquisitionStatus.COMPLETED,
            }
            and self.receipt is None
        ):
            raise ValueError("accepted receipt is required before Artifact finalization")
        if self.receipt is not None and (
            self.receipt.acquisition_ref != self.acquisition_ref
            or self.receipt.run_ref != self.run_ref
        ):
            raise ValueError("receipt does not match acquisition identity")
        return self

    @property
    def resolved_commit_sha(self) -> str | None:
        return None if self.receipt is None else self.receipt.resolved_commit_sha
