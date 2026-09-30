"""Durable, bounded pre-finalization planning assistance. No execution authority."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from boberagent_contracts import InteractionRef
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_values import (
    BindingProvenance,
    EntrypointIntent,
    InvocationLayout,
    OperatorValue,
    ParameterBinding,
    ResolutionState,
)

from boberagent_core.clock import utc_now
from boberagent_core.interactions.errors import InteractionConflict, InteractionNotFound
from boberagent_core.persistence import CoreDatabase
from boberagent_core.persistence.repositories import CoreUnitOfWork

from .construction import CoreExecutionPlanningService, _evidence
from .construction_models import PlanConstructionRequest, PlanConstructionResult
from .interaction_models import CorePlanningInteraction, PlanningInteractionResponse
from .models import (
    PlanningAnswer,
    PlanningAttempt,
    PlanningAttemptLifecycle,
    PlanningAttemptRef,
    PlanningInteractionPurpose,
    PlanProposal,
    PlanProposalRevision,
)


class PlanningAssistanceError(ValueError):
    """Safe bounded-input failure; never includes operator-supplied values."""


class CorePlanningAssistanceService:
    """Answer one exact D4 question, then explicitly pump construction after restart."""

    def __init__(self, database: CoreDatabase, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._database = database
        self._clock = clock

    def get(self, ref: InteractionRef) -> CorePlanningInteraction | None:
        with self._database.unit_of_work() as work:
            item = work.planning_interactions.get(ref)
            return (
                item
                if item and item.request.purpose is not PlanningInteractionPurpose.POLICY_APPROVAL
                else None
            )

    def pending(self, attempt_ref: PlanningAttemptRef) -> tuple[CorePlanningInteraction, ...]:
        with self._database.unit_of_work() as work:
            return tuple(
                item
                for item in work.planning_interactions.list_pending(attempt_ref)
                if item.request.purpose is not PlanningInteractionPurpose.POLICY_APPROVAL
            )

    def respond(self, response: PlanningInteractionResponse) -> CorePlanningInteraction:
        if response.purpose is PlanningInteractionPurpose.POLICY_APPROVAL:
            raise PlanningAssistanceError("ASSISTANCE_PURPOSE_INVALID")
        with self._database.unit_of_work() as work:
            item = work.planning_interactions.get(response.interaction_ref)
            if item is None or item.request.purpose is PlanningInteractionPurpose.POLICY_APPROVAL:
                raise InteractionNotFound("planning assistance Interaction not found")
            request = item.request
            if (
                request.planning_attempt_ref != response.planning_attempt_ref
                or request.proposal_revision != response.proposal_revision
                or request.purpose is not response.purpose
            ):
                raise InteractionConflict("planning answer owner, revision or purpose mismatch")
            if item.response is not None:
                if (
                    item.response.value != response.value
                    or item.response.operator_id != response.operator_id
                ):
                    raise InteractionConflict("conflicting planning answer replay")
                return item
            attempt = work.planning_attempts.get(request.planning_attempt_ref)
            if (
                attempt is None
                or attempt.lifecycle is not PlanningAttemptLifecycle.WAITING_INPUT
                or len(attempt.revisions) != request.proposal_revision
                or attempt.request.mission_ref != request.mission_ref
            ):
                raise InteractionConflict("stale planning assistance context")
            now = self._now()
            revised, parameter_id, answer_value = _apply_answer(work, attempt, item, response)
            accepted = work.planning_interactions.respond(response)
            revision = PlanProposalRevision(
                planning_attempt_ref=attempt.planning_attempt_ref,
                revision_number=len(attempt.revisions) + 1,
                proposal=revised,
                previous_revision_digest=canonical_digest(attempt.revisions[-1]),
                answers=(
                    PlanningAnswer(
                        answer_id=answer_value.answer_id,
                        interaction_ref=request.interaction_ref,
                        planning_attempt_ref=attempt.planning_attempt_ref,
                        parameter_id=parameter_id,
                        operator_id=response.operator_id,
                        value=answer_value,
                        answered_at=now,
                        purpose=request.purpose,
                        proposal_revision=request.proposal_revision,
                    ),
                ),
                created_at=now,
            )
            work.planning_attempts.update_proposal(
                revision,
                expected_state=PlanningAttemptLifecycle.WAITING_INPUT,
                expected_revision=request.proposal_revision,
            )
            return work.planning_interactions.mark_answered(
                accepted.request.interaction_ref, accepted_at=now
            )

    def resume(self, attempt_ref: PlanningAttemptRef) -> PlanConstructionResult:
        with self._database.unit_of_work() as work:
            attempt = work.planning_attempts.get(attempt_ref)
            if attempt is None or not attempt.revisions:
                raise PlanningAssistanceError("ATTEMPT_NOT_FOUND")
            if attempt.lifecycle is not PlanningAttemptLifecycle.WAITING_INPUT:
                raise PlanningAssistanceError("ATTEMPT_NOT_WAITING")
            latest = attempt.revisions[-1]
            if not latest.answers:
                raise PlanningAssistanceError("PLANNING_ANSWER_REQUIRED")
            request = _construction_request(latest.proposal, attempt, len(attempt.revisions))
        return CoreExecutionPlanningService(self._database, clock=self._clock).construct(request)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise PlanningAssistanceError("ASSISTANCE_CLOCK_INVALID")
        return now


def _construction_request(
    proposal: PlanProposal, attempt: PlanningAttempt, revision: int
) -> PlanConstructionRequest:
    if proposal.target is None:
        raise PlanningAssistanceError("TARGET_UNAVAILABLE")
    return PlanConstructionRequest(
        planning_attempt_ref=attempt.planning_attempt_ref,
        expected_revision=revision,
        target=proposal.target,
        invocation=proposal.invocation,
        bindings=proposal.bindings,
        runtime=proposal.runtime,
        limits=proposal.limits,
    )


def _apply_answer(
    work: CoreUnitOfWork,
    attempt: PlanningAttempt,
    item: CorePlanningInteraction,
    response: PlanningInteractionResponse,
) -> tuple[PlanProposal, str, OperatorValue]:
    request = item.request
    proposal = attempt.revisions[-1].proposal
    evidence = _evidence(
        work, attempt, _construction_request(proposal, attempt, len(attempt.revisions))
    )
    answer_id = f"answer-{uuid4().hex}"
    if request.purpose is PlanningInteractionPurpose.PLANNING_ENTRYPOINT_SELECTION:
        if not isinstance(response.value, str) or response.value not in {
            option.option_id for option in request.options
        }:
            raise PlanningAssistanceError("ENTRYPOINT_CHOICE_INVALID")
        entry = next(
            (
                candidate
                for candidate in evidence.semantic.entrypoint_candidates
                if candidate.item_id == response.value
            ),
            None,
        )
        coverage = next(
            (row for row in evidence.semantic.coverage if entry and row.path == entry.source_path),
            None,
        )
        if entry is None or coverage is None or coverage.sha256 is None:
            raise PlanningAssistanceError("ENTRYPOINT_EVIDENCE_STALE")
        selected = EntrypointIntent(
            relative_path=entry.source_path,
            entry_sha256=coverage.sha256,
            language="python",
            invocation_form="SCRIPT",
            evidence_ids=(entry.item_id,),
        )
        return (
            proposal.model_copy(update={"entrypoint": selected}),
            entry.item_id,
            OperatorValue(answer_id=answer_id, value=entry.item_id),
        )
    if request.purpose is PlanningInteractionPurpose.PLANNING_PARAMETER_VALUE:
        parameter_id = request.input_schema.get("parameter_id")
        if (
            not isinstance(parameter_id, str)
            or not isinstance(response.value, int)
            or isinstance(response.value, bool)
        ):
            raise PlanningAssistanceError("PARAMETER_VALUE_INVALID")
        minimum = request.input_schema.get("minimum")
        maximum = request.input_schema.get("maximum")
        if (
            not isinstance(minimum, int)
            or not isinstance(maximum, int)
            or not minimum <= response.value <= maximum
        ):
            raise PlanningAssistanceError("PARAMETER_VALUE_OUT_OF_RANGE")
        binding = next((row for row in proposal.bindings if row.parameter_id == parameter_id), None)
        if binding is None or binding.resolution is not ResolutionState.UNRESOLVED:
            raise PlanningAssistanceError("PARAMETER_BINDING_STALE")
        value = OperatorValue(answer_id=answer_id, value=response.value)
        updated = ParameterBinding.model_validate(
            binding.model_dump()
            | {
                "resolution": ResolutionState.RESOLVED,
                "value": value,
                "provenance": BindingProvenance(
                    origin="OPERATOR", evidence_ids=(parameter_id,), answer_id=answer_id
                ),
            }
        )
        bindings = tuple(
            updated if row.parameter_id == parameter_id else row for row in proposal.bindings
        )
        return (
            proposal.model_copy(update={"bindings": bindings, "unresolved_requirement_ids": ()}),
            parameter_id,
            value,
        )
    if request.purpose is PlanningInteractionPurpose.PLANNING_INVOCATION_LAYOUT:
        if not isinstance(response.value, dict):
            raise PlanningAssistanceError("INVOCATION_LAYOUT_INVALID")
        try:
            layout = InvocationLayout.model_validate(response.value)
        except ValueError:
            raise PlanningAssistanceError("INVOCATION_LAYOUT_INVALID") from None
        if layout.review_id != str(request.interaction_ref):
            raise PlanningAssistanceError("INVOCATION_REVIEW_ID_MISMATCH")
        selected_entrypoint = proposal.entrypoint
        entry = next(
            (
                row
                for row in evidence.semantic.entrypoint_candidates
                if selected_entrypoint and selected_entrypoint.evidence_ids == (row.item_id,)
            ),
            None,
        )
        if entry is None or set(layout.evidence_ids) != set(entry.parameter_candidate_refs):
            raise PlanningAssistanceError("INVOCATION_EVIDENCE_MISMATCH")
        return (
            proposal.model_copy(update={"invocation": layout}),
            "invocation-layout",
            OperatorValue(answer_id=answer_id, value=canonical_digest(layout)),
        )
    raise PlanningAssistanceError("ASSISTANCE_PURPOSE_UNSUPPORTED")
