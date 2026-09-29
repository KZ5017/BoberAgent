"""D4 explicit reviewed inputs and metadata-only validation snapshots."""

from typing import Literal

from boberagent_contracts import AssetRef, MissionRef
from boberagent_contracts._base import FrozenContractModel
from boberagent_contracts.plan_requirements import ExecutionLimits, RuntimeRequirement
from boberagent_contracts.plan_values import InvocationLayout, ParameterBinding, PlanTarget
from pydantic import Field, StrictInt

from boberagent_core.inspections.semantic_models import SemanticInspectionDocument
from boberagent_core.models import Asset, Service

from .models import (
    PlanningAttempt,
    PlanningAttemptRef,
    PlanValidation,
    PlanValidationReason,
    PlanValidationStatus,
)


class PlanningScopeAsset(FrozenContractModel):
    asset_ref: AssetRef
    address: str


class PlanningScope(FrozenContractModel):
    """Current bootstrap scope: Mission-owned Assets, not a new scope policy."""

    mission_ref: MissionRef
    assets: tuple[PlanningScopeAsset, ...] = Field(
        json_schema_extra={"collection_semantics": "set"}
    )


class PlanConstructionRequest(FrozenContractModel):
    planning_attempt_ref: PlanningAttemptRef
    expected_revision: StrictInt = Field(ge=0)
    target: PlanTarget
    # Existing D1 InvocationLayout is the reviewed, provenance-bearing input.
    invocation: InvocationLayout | None = None
    bindings: tuple[ParameterBinding, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    runtime: RuntimeRequirement | None = None
    limits: ExecutionLimits | None = None


class PlanningEvidence(FrozenContractModel):
    """Validated authoritative metadata; no source bytes or runtime handles."""

    attempt: PlanningAttempt
    semantic: SemanticInspectionDocument
    scope: PlanningScope
    asset: Asset | None
    service: Service | None


class ConstructionAssessment(FrozenContractModel):
    status: PlanValidationStatus
    reasons: tuple[PlanValidationReason, ...] = Field(min_length=1)


class PlanConstructionResult(FrozenContractModel):
    attempt: PlanningAttempt
    validation: PlanValidation | None = None
    policy: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    execution_readiness: Literal["NOT_ASSESSED"] = "NOT_ASSESSED"
