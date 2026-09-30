"""Core-only planning questions and answers; never capability Run interactions."""

from typing import Self

from boberagent_contracts import (
    InteractionLifecycle,
    InteractionRef,
    JsonObject,
    JsonValue,
    MissionRef,
)
from boberagent_contracts._base import FrozenContractModel, ShortStr, SymbolicName
from boberagent_contracts.interaction import InteractionOption
from pydantic import AwareDatetime, Field, StrictInt, model_validator

from .models import PlanningAttemptRef, PlanningInteractionPurpose
from .records import PlanDecisionRef


class PlanningInteractionRequest(FrozenContractModel):
    """Bounded question pinned to one attempt/revision or one D5 assessment."""

    interaction_ref: InteractionRef
    planning_attempt_ref: PlanningAttemptRef
    mission_ref: MissionRef
    proposal_revision: StrictInt = Field(ge=0)
    purpose: PlanningInteractionPurpose
    title: ShortStr
    description: ShortStr
    input_schema: JsonObject
    options: tuple[InteractionOption, ...] = Field(default=(), max_length=32)
    policy_decision_ref: PlanDecisionRef | None = None
    policy_context_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def shape(self) -> Self:
        approval = self.purpose is PlanningInteractionPurpose.POLICY_APPROVAL
        if approval != (self.policy_decision_ref is not None) or approval != (
            self.policy_context_fingerprint is not None
        ):
            raise ValueError("approval must bind one exact policy assessment")
        schema_type = self.input_schema.get("type")
        if self.options:
            ids = tuple(option.option_id for option in self.options)
            if (
                len(set(ids)) != len(ids)
                or schema_type != "string"
                or self.input_schema.get("enum") != list(ids)
            ):
                raise ValueError("choice schema must exactly match bounded options")
        elif schema_type not in {"integer", "object"}:
            raise ValueError("planning input schema is unsupported")
        if approval and tuple(option.option_id for option in self.options) != ("APPROVE", "DENY"):
            raise ValueError("approval requires APPROVE or DENY only")
        return self


class PlanningInteractionResponse(FrozenContractModel):
    interaction_ref: InteractionRef
    planning_attempt_ref: PlanningAttemptRef
    proposal_revision: StrictInt = Field(ge=0)
    purpose: PlanningInteractionPurpose
    operator_id: SymbolicName
    value: JsonValue
    responded_at: AwareDatetime


class CorePlanningInteraction(FrozenContractModel):
    request: PlanningInteractionRequest
    state: InteractionLifecycle
    response: PlanningInteractionResponse | None = None
    accepted_at: AwareDatetime | None = None
