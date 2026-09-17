"""Controlled Result ingestion errors."""


class ResultIngestionError(RuntimeError):
    """Base error for Core semantic Result ingestion."""


class ConflictingResultError(ResultIngestionError):
    """One CapabilityRunRef was associated with different terminal Results."""


class ResultProvenanceError(ResultIngestionError):
    """Result content does not belong to its persisted Run/routing provenance."""
