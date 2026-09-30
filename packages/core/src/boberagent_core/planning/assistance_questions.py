"""Bounded Core-local questions derived only from a D4 REQUIRES_INPUT result."""

from datetime import datetime
from uuid import uuid4

from boberagent_contracts import InteractionRef, JsonObject
from boberagent_contracts.interaction import InteractionOption
from boberagent_contracts.plan_values import NetworkTarget

from .construction_models import ConstructionAssessment, PlanningEvidence
from .interaction_models import PlanningInteractionRequest
from .models import PlanningAttempt, PlanningInteractionPurpose
from .models import PlanValidationReasonCode as Code


def question_for_wait(
    attempt: PlanningAttempt,
    assessment: ConstructionAssessment,
    evidence: PlanningEvidence,
    now: datetime,
) -> PlanningInteractionRequest | None:
    """Return one supported question; all other unresolved semantics stay fail-closed."""
    if len(assessment.reasons) != 1 or not attempt.revisions:
        return None
    reason = assessment.reasons[0]
    purpose: PlanningInteractionPurpose
    schema: JsonObject
    options: tuple[InteractionOption, ...] = ()
    if reason.code is Code.ENTRYPOINT_SELECTION_REQUIRED:
        eligible = {item.item_id for item in evidence.semantic.entrypoint_candidates}
        ids = tuple(sorted(set(reason.evidence_refs) & eligible))
        if len(ids) < 2:
            return None
        purpose = PlanningInteractionPurpose.PLANNING_ENTRYPOINT_SELECTION
        options = tuple(InteractionOption(option_id=item, label=item) for item in ids)
        schema = {"type": "string", "enum": list(ids)}
    elif reason.code is Code.UNRESOLVED_BINDING:
        ids = reason.evidence_refs
        if len(ids) != 1:
            return None
        parameter = next(
            (item for item in evidence.semantic.parameter_candidates if item.item_id == ids[0]),
            None,
        )
        if parameter is None or parameter.role.value not in {"TARGET_PORT", "TIMEOUT"}:
            return None
        proposal = attempt.revisions[-1].proposal
        if parameter.role.value == "TARGET_PORT":
            target = proposal.target
            if (
                not isinstance(target, NetworkTarget)
                or target.port is None
                or not 1 <= target.port <= 65535
            ):
                return None
            minimum = maximum = target.port
        else:
            if proposal.limits is None:
                return None
            minimum, maximum = 1, proposal.limits.wall_time_seconds
        purpose = PlanningInteractionPurpose.PLANNING_PARAMETER_VALUE
        schema = {
            "type": "integer",
            "minimum": minimum,
            "maximum": maximum,
            "parameter_id": ids[0],
        }
    elif reason.code is Code.INVOCATION_LAYOUT_REQUIRED:
        purpose = PlanningInteractionPurpose.PLANNING_INVOCATION_LAYOUT
        schema = {
            "type": "object",
            "required": ["origin", "review_id", "evidence_ids", "arguments"],
            "additionalProperties": False,
        }
    else:
        return None
    return PlanningInteractionRequest(
        interaction_ref=InteractionRef(f"interaction-plan-{uuid4().hex}"),
        planning_attempt_ref=attempt.planning_attempt_ref,
        mission_ref=attempt.request.mission_ref,
        proposal_revision=len(attempt.revisions),
        purpose=purpose,
        title="Resolve bounded planning input",
        description="This answer is planning input, not source evidence or policy approval.",
        input_schema=schema,
        options=options,
        requested_at=now,
    )
