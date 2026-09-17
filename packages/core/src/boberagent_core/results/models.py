"""Core-owned durable CapabilityResult ingestion snapshots."""

from enum import StrEnum
from typing import Annotated

from boberagent_contracts import CapabilityResult, CapabilityRunRef
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


class ResultIngestionStatus(StrEnum):
    """Semantic processing lifecycle, distinct from transport receipt."""

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    PARTIALLY_PROCESSED = "PARTIALLY_PROCESSED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"

    @property
    def is_complete(self) -> bool:
        return self in {
            ResultIngestionStatus.PROCESSED,
            ResultIngestionStatus.PARTIALLY_PROCESSED,
            ResultIngestionStatus.REJECTED,
        }


Sha256Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ResultIngestion(BaseModel):
    """Canonical Result plus durable semantic processing metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_ref: CapabilityRunRef
    result_fingerprint: Sha256Fingerprint
    result: CapabilityResult
    transport_message_id: str | None = Field(default=None, min_length=1, max_length=255)
    source_node_id: str | None = Field(default=None, min_length=1, max_length=255)
    status: ResultIngestionStatus
    received_at: AwareDatetime
    updated_at: AwareDatetime
    processed_at: AwareDatetime | None = None
    processing_attempts: int = Field(ge=0)
    materialized_count: int = Field(ge=0)
    unsupported_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    error: str | None = None
    conflict_count: int = Field(ge=0)
    last_conflict_fingerprint: Sha256Fingerprint | None = None
    last_conflict_at: AwareDatetime | None = None
