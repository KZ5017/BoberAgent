"""Bounded safe admission errors; invalid provenance is not an unsupported PoC."""

from enum import StrEnum


class AdmissionErrorCode(StrEnum):
    REQUEST_INVALID = "REQUEST_INVALID"
    UPSTREAM_NOT_FOUND = "UPSTREAM_NOT_FOUND"
    RECORD_INVALID = "RECORD_INVALID"
    OWNERSHIP_MISMATCH = "OWNERSHIP_MISMATCH"
    ACQUISITION_NOT_COMPLETED = "ACQUISITION_NOT_COMPLETED"
    C2_NOT_COMPLETED = "C2_NOT_COMPLETED"
    C3_NOT_COMPLETED = "C3_NOT_COMPLETED"
    PROFILE_UNSUPPORTED = "PROFILE_UNSUPPORTED"
    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    C3_PARENT_MISMATCH = "C3_PARENT_MISMATCH"
    ARTIFACT_MISMATCH = "ARTIFACT_MISMATCH"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class PlanningAdmissionError(ValueError):
    def __init__(self, code: AdmissionErrorCode) -> None:
        self.code = code
        super().__init__(code.value)
