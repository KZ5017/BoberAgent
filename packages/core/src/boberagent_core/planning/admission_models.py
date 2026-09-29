"""Core-only evidence admission, distinct from validation, policy and planning."""

from enum import StrEnum
from typing import Literal, Self

from boberagent_contracts import MissionRef, PoCAcquisitionRef
from boberagent_contracts._base import FrozenContractModel, NonEmptyStr, SymbolicName
from pydantic import Field, model_validator

from boberagent_core.inspections.classification_models import SupportClassification
from boberagent_core.inspections.identity import PoCInspectionRef

from .models import PlanningAttempt


class PlanningAdmissionRequest(FrozenContractModel):
    """Only identities are caller input. Documents, hashes and ownership come from Core."""

    mission_ref: MissionRef
    acquisition_ref: PoCAcquisitionRef
    semantic_inspection_ref: PoCInspectionRef
    classification_inspection_ref: PoCInspectionRef
    planner_profile: Literal["m20-d-planning"]
    planner_version: Literal["1"]
    policy_profile: SymbolicName = Field(max_length=128)
    policy_version: NonEmptyStr = Field(max_length=128)


class PlanningAdmissionOutcome(StrEnum):
    ELIGIBLE_AUTOMATIC = "ELIGIBLE_AUTOMATIC"
    ELIGIBLE_ASSISTED = "ELIGIBLE_ASSISTED"
    REJECTED_UNSUPPORTED = "REJECTED_UNSUPPORTED"


class PlanningAdmissionResult(FrozenContractModel):
    """Snapshot of C3 admission, not plan validity, approval or permission."""

    outcome: PlanningAdmissionOutcome
    attempt: PlanningAttempt

    @model_validator(mode="after")
    def consistent_classification(self) -> Self:
        expected = {
            SupportClassification.AUTOMATIC: PlanningAdmissionOutcome.ELIGIBLE_AUTOMATIC,
            SupportClassification.ASSISTED: PlanningAdmissionOutcome.ELIGIBLE_ASSISTED,
            SupportClassification.UNSUPPORTED: PlanningAdmissionOutcome.REJECTED_UNSUPPORTED,
        }[self.attempt.request.inspection.classification.classification]
        if self.outcome is not expected:
            raise ValueError("admission must preserve authoritative classification")
        return self
