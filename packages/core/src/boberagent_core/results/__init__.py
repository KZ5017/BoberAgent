"""Core-owned CapabilityResult ingestion boundary."""

from .errors import (
    ConflictingResultError,
    ResultIngestionError,
    ResultProvenanceError,
)
from .models import ResultIngestion, ResultIngestionStatus
from .service import ResultIngestionService, result_fingerprint

__all__ = [
    "ConflictingResultError",
    "ResultIngestion",
    "ResultIngestionError",
    "ResultIngestionService",
    "ResultIngestionStatus",
    "ResultProvenanceError",
    "result_fingerprint",
]
