"""Core-local D6 operator policy approval; no execution authority or transport."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from boberagent_contracts import ExecutionPlanRef, InteractionLifecycle, InteractionRef
from boberagent_contracts.interaction import InteractionOption

from boberagent_core.clock import utc_now
from boberagent_core.interactions.errors import InteractionConflict, InteractionNotFound
from boberagent_core.persistence import CoreDatabase
from boberagent_core.persistence.repositories import CoreUnitOfWork

from .fingerprints import decision_context_fingerprint
from .interaction_models import (
    CorePlanningInteraction,
    PlanningInteractionRequest,
    PlanningInteractionResponse,
)
from .models import (
    OperatorPlanApproval,
    PlanningAttemptLifecycle,
    PlanningDisposition,
    PlanningInteractionPurpose,
    PlanPolicyDecision,
    PlanValidationStatus,
)
from .policy_service import CorePlanPolicyService
from .records import (
    ApprovalDocument,
    PlanDecisionRecord,
    PlanDecisionRef,
    PolicyDocument,
    ValidationDocument,
)


class PlanApprovalError(ValueError):
    """Bounded approval failure; never renders source or sensitive values."""


class CorePlanApprovalService:
    """Explicit request/response pump over exact current D5 assessment history."""

    def __init__(
        self,
        database: CoreDatabase,
        policy: CorePlanPolicyService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._policy = policy
        self._clock = clock

    def request(self, plan_ref: ExecutionPlanRef) -> CorePlanningInteraction:
        assessment = self._policy.evaluate(plan_ref)
        policy_record = assessment.record
        if not isinstance(policy_record.document, PolicyDocument) or (
            policy_record.document.value.decision is not PlanPolicyDecision.REQUIRES_APPROVAL
        ):
            raise PlanApprovalError("POLICY_APPROVAL_NOT_REQUIRED")
        with self._database.unit_of_work() as work:
            stored = work.execution_plans.get(plan_ref)
            if stored is None:
                raise PlanApprovalError("PLAN_NOT_FOUND")
            attempt = work.planning_attempts.get(stored.planning_attempt_ref)
            if (
                attempt is None
                or attempt.lifecycle is not PlanningAttemptLifecycle.COMPLETED
                or (attempt.disposition is not PlanningDisposition.VALID)
            ):
                raise PlanApprovalError("PLAN_NOT_VALIDATED")
            if work.plan_decisions.get(policy_record.decision_ref) != policy_record:
                raise PlanApprovalError("POLICY_ASSESSMENT_CHANGED")
            request = PlanningInteractionRequest(
                interaction_ref=InteractionRef(f"interaction-plan-{uuid4().hex}"),
                planning_attempt_ref=attempt.planning_attempt_ref,
                mission_ref=stored.plan.mission_ref,
                proposal_revision=len(attempt.revisions),
                purpose=PlanningInteractionPurpose.POLICY_APPROVAL,
                title="Review ExecutionPlan policy assessment",
                description="Approve or deny this exact assessed plan. Approval is not execution authorization.",
                input_schema={"type": "string", "enum": ["APPROVE", "DENY"]},
                options=(
                    InteractionOption(option_id="APPROVE", label="Approve"),
                    InteractionOption(option_id="DENY", label="Deny"),
                ),
                policy_decision_ref=policy_record.decision_ref,
                policy_context_fingerprint=decision_context_fingerprint(policy_record.context),
                requested_at=self._now(),
            )
            return work.planning_interactions.create(request)

    def get(self, ref: InteractionRef) -> CorePlanningInteraction | None:
        with self._database.unit_of_work() as work:
            interaction = work.planning_interactions.get(ref)
            return (
                interaction
                if interaction is not None
                and interaction.request.purpose is PlanningInteractionPurpose.POLICY_APPROVAL
                else None
            )

    def respond(self, response: PlanningInteractionResponse) -> PlanDecisionRecord:
        if (
            response.purpose is not PlanningInteractionPurpose.POLICY_APPROVAL
            or not isinstance(response.value, str)
            or response.value not in {"APPROVE", "DENY"}
        ):
            raise PlanApprovalError("APPROVAL_RESPONSE_INVALID")
        with self._database.unit_of_work() as work:
            current = work.planning_interactions.get(response.interaction_ref)
            if (
                current is None
                or current.request.purpose is not PlanningInteractionPurpose.POLICY_APPROVAL
            ):
                raise InteractionNotFound("unknown policy approval Interaction")
            request = current.request
            stored = work.execution_plans.get_by_attempt(request.planning_attempt_ref)
            if stored is None or request.mission_ref != stored.plan.mission_ref:
                raise PlanApprovalError("APPROVAL_PLAN_MISMATCH")
            plan_ref = stored.plan.execution_plan_id
        assessment = self._policy.evaluate(plan_ref)
        policy_record = assessment.record
        if (
            policy_record.decision_ref != request.policy_decision_ref
            or decision_context_fingerprint(policy_record.context)
            != request.policy_context_fingerprint
            or not isinstance(policy_record.document, PolicyDocument)
            or policy_record.document.value.decision is not PlanPolicyDecision.REQUIRES_APPROVAL
        ):
            raise PlanApprovalError("POLICY_ASSESSMENT_STALE")
        with self._database.unit_of_work() as work:
            current = work.planning_interactions.get(response.interaction_ref)
            if current is None or current.request != request:
                raise InteractionConflict("policy approval Interaction changed")
            attempt = work.planning_attempts.get(request.planning_attempt_ref)
            if (
                attempt is None
                or attempt.lifecycle is not PlanningAttemptLifecycle.COMPLETED
                or (
                    attempt.disposition is not PlanningDisposition.VALID
                    or len(attempt.revisions) != request.proposal_revision
                )
            ):
                raise PlanApprovalError("APPROVAL_ATTEMPT_STALE")
            work.planning_interactions.respond(response)
            existing = _approval_for(work, plan_ref, policy_record.decision_ref)
            if existing is not None:
                if not isinstance(existing.document, ApprovalDocument) or (
                    existing.document.value.interaction_ref != request.interaction_ref
                    or existing.document.value.operator_id != response.operator_id
                    or existing.document.value.decision
                    != ("APPROVE" if response.value == "APPROVE" else "REJECT")
                ):
                    raise InteractionConflict("conflicting policy approval replay")
                work.planning_interactions.mark_answered(
                    request.interaction_ref, accepted_at=existing.created_at
                )
                return existing
            validation = _matching_validation(work, plan_ref)
            now = self._now()
            value = policy_record.document.value
            record = PlanDecisionRecord(
                decision_ref=PlanDecisionRef(f"plan-decision-{uuid4().hex}"),
                document=ApprovalDocument(
                    value=OperatorPlanApproval(
                        execution_plan_ref=plan_ref,
                        intent_sha256=value.intent_sha256,
                        mission_ref=value.mission_ref,
                        scope_sha256=value.scope_sha256,
                        policy_profile=value.policy_profile,
                        policy_version=value.policy_version,
                        policy_decision_ref=policy_record.decision_ref,
                        validation_decision_ref=validation.decision_ref,
                        policy_sha256=value.policy_sha256,
                        policy_context_fingerprint=request.policy_context_fingerprint,
                        interaction_ref=request.interaction_ref,
                        decision="APPROVE" if response.value == "APPROVE" else "REJECT",
                        operator_id=response.operator_id,
                        decided_at=now,
                    )
                ),
                context=policy_record.context,
                created_at=now,
            )
            persisted = work.plan_decisions.append(record)
            work.planning_interactions.mark_answered(request.interaction_ref, accepted_at=now)
            return persisted

    def get_applicable_approval(self, plan_ref: ExecutionPlanRef) -> PlanDecisionRecord | None:
        """Current exact APPROVE lookup only; never an execution admission check."""
        assessment = self._policy.evaluate(plan_ref)
        record = assessment.record
        if not isinstance(record.document, PolicyDocument) or (
            record.document.value.decision is not PlanPolicyDecision.REQUIRES_APPROVAL
        ):
            return None
        with self._database.unit_of_work() as work:
            approval = _approval_for(work, plan_ref, record.decision_ref)
            if approval is None or not isinstance(approval.document, ApprovalDocument):
                return None
            value = approval.document.value
            interaction = (
                work.planning_interactions.get(value.interaction_ref)
                if value.interaction_ref
                else None
            )
            if (
                value.decision != "APPROVE"
                or value.policy_sha256 != record.document.value.policy_sha256
                or value.validation_decision_ref
                != _matching_validation(work, plan_ref).decision_ref
                or interaction is None
                or interaction.state is not InteractionLifecycle.ANSWERED
                or interaction.response is None
                or interaction.response.value != "APPROVE"
                or interaction.request.policy_decision_ref != record.decision_ref
                or value.policy_context_fingerprint != decision_context_fingerprint(record.context)
            ):
                return None
            return approval

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise PlanApprovalError("APPROVAL_CLOCK_INVALID")
        return now


def _matching_validation(work: CoreUnitOfWork, plan_ref: ExecutionPlanRef) -> PlanDecisionRecord:
    records = tuple(
        item
        for item in work.plan_decisions.list_for_plan(plan_ref)
        if isinstance(item.document, ValidationDocument)
        and item.document.value.status is PlanValidationStatus.VALID
        and (item.document.value.validation_profile, item.document.value.validation_version)
        == ("m20-d4-plan-validator", "1")
    )
    if len(records) != 1:
        raise PlanApprovalError("VALIDATION_UNAVAILABLE")
    return records[0]


def _approval_for(
    work: CoreUnitOfWork, plan_ref: ExecutionPlanRef, policy_ref: PlanDecisionRef
) -> PlanDecisionRecord | None:
    found = tuple(
        item
        for item in work.plan_decisions.list_for_plan(plan_ref)
        if isinstance(item.document, ApprovalDocument)
        and item.document.value.policy_decision_ref == policy_ref
    )
    if len(found) > 1:
        raise PlanApprovalError("APPROVAL_HISTORY_CONFLICT")
    return found[0] if found else None
