"""Explicit D4 construction pump. No policy, byte access, dispatch or execution."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from boberagent_contracts import ExecutionPlanRef, ExecutionPlanV2, execution_intent_digest
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_requirements import (
    EffectScope,
    ExpectedEvidence,
    FilesystemConstraints,
    NetworkConstraints,
    NetworkDestinationClass,
    NetworkRule,
    PlanDependency,
    PlanDependencyKind,
)
from boberagent_contracts.plan_values import EntrypointIntent, MissionTargetValue, NetworkTarget

from boberagent_core.clock import utc_now
from boberagent_core.inspections.semantic_models import (
    DependencyKind,
    EpistemicState,
    ImportKind,
    SemanticInspectionDocument,
    SourceOrigin,
)
from boberagent_core.persistence import CoreDatabase
from boberagent_core.persistence.repositories import CoreUnitOfWork

from .admission import _authoritative_request
from .admission_models import PlanningAdmissionRequest
from .assistance_questions import question_for_wait
from .construction_models import (
    PlanConstructionRequest,
    PlanConstructionResult,
    PlanningEvidence,
    PlanningScope,
    PlanningScopeAsset,
)
from .errors import PlanningConflict
from .models import (
    DecisionContext,
    InitialPlanPolicyProfile,
    PlanningAttempt,
    PlanningAttemptRef,
    PlanProposal,
    PlanProposalRevision,
    PlanValidation,
)
from .models import (
    PlanningAttemptLifecycle as State,
)
from .models import (
    PlanningDisposition as Disposition,
)
from .models import (
    PlanValidationStatus as Status,
)
from .records import PlanDecisionRecord, PlanDecisionRef, ValidationDocument
from .validation import (
    VALIDATOR_PROFILE,
    VALIDATOR_VERSION,
    assess_proposal,
    check_model_fields,
    validate_plan,
)


class PlanningConstructionError(ValueError):
    """Safe code-only errors; no source/parameter/exception payload rendering."""


class CoreExecutionPlanningService:
    """Immediate, revision-CAS pump; a VALID plan still has no permission.

    Identical finalized/waiting proposals return history unchanged. A different
    finalized input conflicts. Active stale revisions conflict, never overwrite.
    The complete transition (revision, plan, validation, completion) is one UoW.
    """

    def __init__(self, database: CoreDatabase, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._database = database
        self._clock = clock

    def get(self, attempt_ref: PlanningAttemptRef) -> PlanConstructionResult | None:
        with self._database.unit_of_work() as work:
            attempt = work.planning_attempts.get(attempt_ref)
            return None if attempt is None else _result(work, attempt)

    def construct(self, request: PlanConstructionRequest) -> PlanConstructionResult:
        try:
            check_model_fields(request)
            request = PlanConstructionRequest.model_validate_json(request.model_dump_json())
        except (ValueError, TypeError, AttributeError):
            raise PlanningConstructionError("CONSTRUCTION_REQUEST_INVALID") from None
        try:
            with self._database.unit_of_work() as work:
                attempt = work.planning_attempts.get(request.planning_attempt_ref)
                if attempt is None:
                    raise PlanningConstructionError("ATTEMPT_NOT_FOUND")
                if attempt.disposition is Disposition.UNSUPPORTED:
                    raise PlanningConstructionError("ADMISSION_UNSUPPORTED")
                evidence = _evidence(work, attempt, request)
                proposal = _proposal(request, evidence)
                if attempt.lifecycle.is_terminal or attempt.lifecycle is State.WAITING_INPUT:
                    if (
                        attempt.revisions
                        and canonical_digest(
                            attempt.revisions[-1].proposal,
                            exclude=frozenset({"unresolved_requirement_ids"}),
                        )
                        == canonical_digest(
                            proposal, exclude=frozenset({"unresolved_requirement_ids"})
                        )
                        and (attempt.lifecycle.is_terminal or not attempt.revisions[-1].answers)
                    ):
                        return _result(work, attempt)
                    if attempt.lifecycle.is_terminal:
                        raise PlanningConflict("finalized construction input conflict")
                if attempt.lifecycle not in {State.REQUESTED, State.WAITING_INPUT} or (
                    len(attempt.revisions) != request.expected_revision
                ):
                    raise PlanningConflict("stale construction revision or lifecycle")
                now = self._clock()
                if now.tzinfo is None or now.utcoffset() != timedelta(0):
                    raise PlanningConstructionError("CONSTRUCTION_CLOCK_INVALID")
                # Evaluate pure snapshots before any write. No speculative authority.
                assessment = assess_proposal(proposal, evidence)
                if assessment.status is Status.REQUIRES_INPUT:
                    proposal = PlanProposal.model_validate(
                        proposal.model_dump()
                        | {
                            "unresolved_requirement_ids": tuple(
                                reason.code.value for reason in assessment.reasons
                            )
                        }
                    )
                attempt = work.planning_attempts.update_lifecycle(
                    attempt.planning_attempt_ref,
                    State.EVALUATING,
                    expected_state=attempt.lifecycle,
                    expected_revision=request.expected_revision,
                    updated_at=now,
                )
                revision = PlanProposalRevision(
                    planning_attempt_ref=attempt.planning_attempt_ref,
                    revision_number=request.expected_revision + 1,
                    proposal=proposal,
                    previous_revision_digest=canonical_digest(attempt.revisions[-1])
                    if attempt.revisions
                    else None,
                    created_at=now,
                )
                attempt = work.planning_attempts.update_proposal(
                    revision,
                    expected_state=State.EVALUATING,
                    expected_revision=request.expected_revision,
                )
                codes = tuple(reason.code.value for reason in assessment.reasons)
                if assessment.status is not Status.VALID:
                    waiting = assessment.status is Status.REQUIRES_INPUT
                    attempt = work.planning_attempts.update_lifecycle(
                        attempt.planning_attempt_ref,
                        State.WAITING_INPUT if waiting else State.COMPLETED,
                        expected_state=State.EVALUATING,
                        expected_revision=len(attempt.revisions),
                        updated_at=now,
                        disposition=Disposition.REQUIRES_INPUT if waiting else Disposition.INVALID,
                        diagnostic_codes=codes,
                    )
                    if waiting:
                        question = question_for_wait(attempt, assessment, evidence, now)
                        if question is not None:
                            work.planning_interactions.create(question)
                    return _result(work, attempt)
                candidate = _candidate(proposal, attempt, now)
                final_assessment = validate_plan(candidate, evidence)
                if final_assessment.status is not Status.VALID:
                    raise PlanningConstructionError("CANDIDATE_VALIDATION_INCONSISTENT")
                digest = execution_intent_digest(candidate)
                scope_digest = canonical_digest(evidence.scope)
                validation = PlanValidation(
                    execution_plan_ref=candidate.execution_plan_id,
                    intent_sha256=digest,
                    mission_ref=candidate.mission_ref,
                    scope_sha256=scope_digest,
                    validation_profile=VALIDATOR_PROFILE,
                    validation_version=VALIDATOR_VERSION,
                    status=Status.VALID,
                    reasons=final_assessment.reasons,
                    assessed_at=now,
                )
                work.planning_attempts.finalize(
                    attempt.planning_attempt_ref,
                    candidate,
                    intent_sha256=digest,
                    expected_state=State.EVALUATING,
                    expected_revision=len(attempt.revisions),
                    completed_at=now,
                )
                # D2 finalize and append share the same outer transaction. Any append
                # failure rolls back the plan, VALID completion and proposal revision.
                work.plan_decisions.append(
                    PlanDecisionRecord(
                        decision_ref=PlanDecisionRef(f"plan-decision-{uuid4().hex}"),
                        document=ValidationDocument(value=validation),
                        context=DecisionContext(
                            mission_ref=candidate.mission_ref,
                            intent_sha256=digest,
                            scope_sha256=scope_digest,
                            classification_sha256=attempt.request.inspection.classification_sha256,
                            validation_profile=VALIDATOR_PROFILE,
                            validation_version=VALIDATOR_VERSION,
                            # Profile identity/budget declaration only, never an assessment.
                            policy=InitialPlanPolicyProfile(maximum_limits=candidate.limits),
                        ),
                        created_at=now,
                    )
                )
                finished = work.planning_attempts.get(attempt.planning_attempt_ref)
                if finished is None:
                    raise PlanningConstructionError("CONSTRUCTION_INTERNAL_ERROR")
                return _result(work, finished)
        except (PlanningConstructionError, PlanningConflict):
            raise
        except Exception:
            raise PlanningConstructionError("CONSTRUCTION_INTERNAL_ERROR") from None


def _evidence(
    work: CoreUnitOfWork, attempt: PlanningAttempt, request: PlanConstructionRequest
) -> PlanningEvidence:
    original = attempt.request
    if (original.policy_profile, original.policy_version) != ("m20-python-single-target", "1"):
        raise PlanningConstructionError("CONSTRUCTION_PROFILE_UNSUPPORTED")
    canonical = _authoritative_request(
        work,
        PlanningAdmissionRequest(
            mission_ref=original.mission_ref,
            acquisition_ref=original.source.acquisition_ref,
            semantic_inspection_ref=original.inspection.classification.semantic_inspection_ref,
            classification_inspection_ref=original.inspection.classification_ref,
            planner_profile=original.profile,
            planner_version=original.profile_version,
            policy_profile=original.policy_profile,
            policy_version=original.policy_version,
        ),
    )
    if canonical != original:
        raise PlanningConstructionError("ADMISSION_IDENTITY_MISMATCH")
    c2 = work.inspections.get(canonical.inspection.classification.semantic_inspection_ref)
    if c2 is None or not isinstance(c2.document, SemanticInspectionDocument):
        raise PlanningConstructionError("EVIDENCE_NOT_FOUND")
    target = request.target
    asset = work.assets.get(target.asset_ref) if isinstance(target, NetworkTarget) else None
    service = (
        work.services.get(target.service_ref)
        if isinstance(target, NetworkTarget) and target.service_ref
        else None
    )
    return PlanningEvidence(
        attempt=attempt,
        semantic=c2.document,
        asset=asset,
        service=service,
        scope=PlanningScope(
            mission_ref=canonical.mission_ref,
            assets=tuple(
                PlanningScopeAsset(asset_ref=item.asset_ref, address=item.primary_address)
                for item in work.assets.list_for_mission(canonical.mission_ref)
            ),
        ),
    )


def _proposal(request: PlanConstructionRequest, evidence: PlanningEvidence) -> PlanProposal:
    semantic = evidence.semantic
    eligible = tuple(
        item
        for item in semantic.entrypoint_candidates
        if (
            item.origin is SourceOrigin.CODE
            and item.epistemic_state is EpistemicState.OBSERVED
            and item.runtime == "python"
            and item.invocation_style == "SCRIPT_MAIN_GUARD"
        )
    )
    entrypoint = None
    if len(eligible) == 1:
        entry = eligible[0]
        coverage = next(
            (item for item in semantic.coverage if item.path == entry.source_path), None
        )
        if coverage is not None and coverage.sha256 is not None:
            entrypoint = EntrypointIntent(
                relative_path=entry.source_path,
                entry_sha256=coverage.sha256,
                language=entry.runtime,
                invocation_form="SCRIPT",
                evidence_ids=(entry.item_id,),
            )
    if evidence.attempt.revisions:
        prior = evidence.attempt.revisions[-1].proposal.entrypoint
        if prior is not None and any(prior.evidence_ids == (item.item_id,) for item in eligible):
            entrypoint = prior

    target = request.target
    host = next(
        (item for item in request.bindings if isinstance(item.value, MissionTargetValue)), None
    )
    rules = (
        ()
        if not isinstance(target, NetworkTarget) or target.port is None or target.transport is None
        else (
            NetworkRule(
                destination=NetworkDestinationClass.SELECTED_TARGET,
                endpoint_binding_id=host.binding_id if host else None,
                transport=target.transport,
                ports=(target.port,),
            ),
        )
    )
    return PlanProposal(
        source=evidence.attempt.request.source,
        target=target,
        entrypoint=entrypoint,
        runtime=request.runtime,
        invocation=request.invocation,
        bindings=request.bindings,
        dependencies=tuple(
            PlanDependency(
                dependency_id=item.item_id,
                kind=(
                    PlanDependencyKind.STDLIB_MODULE
                    if item.kind is DependencyKind.IMPORTED_MODULE
                    and item.import_kind is ImportKind.STDLIB_LOOKING
                    else PlanDependencyKind.UNKNOWN
                ),
                identifier=item.name,
                version_constraint=item.version_constraint,
                evidence_ids=(item.item_id,),
            )
            for item in semantic.dependency_observations
        ),
        filesystem=FilesystemConstraints(scope=EffectScope.BOUNDED, cleanup="RETAIN_EVIDENCE"),
        network=NetworkConstraints(rules=rules),
        limits=request.limits,
        expected_evidence=(
            ExpectedEvidence(evidence_id="stdout", kind="STDOUT", semantic_type="poc.stdout"),
            ExpectedEvidence(evidence_id="stderr", kind="STDERR", semantic_type="poc.stderr"),
        ),
    )


def _candidate(proposal: PlanProposal, attempt: PlanningAttempt, now: datetime) -> ExecutionPlanV2:
    # Full model validation is an additional schema gate, not a policy evaluator.
    return ExecutionPlanV2.model_validate(
        proposal.model_dump(exclude={"unresolved_requirement_ids"})
        | {
            "execution_plan_id": ExecutionPlanRef(f"execution-plan-{uuid4().hex}"),
            "mission_ref": attempt.request.mission_ref,
            "created_at": now,
        }
    )


def _result(work: CoreUnitOfWork, attempt: PlanningAttempt) -> PlanConstructionResult:
    validation = None
    if attempt.finalized_plan is not None:
        decisions = tuple(
            item.document.value
            for item in work.plan_decisions.list_for_plan(attempt.finalized_plan.execution_plan_id)
            if isinstance(item.document, ValidationDocument)
            and (
                item.document.value.validation_profile == VALIDATOR_PROFILE
                and item.document.value.validation_version == VALIDATOR_VERSION
            )
        )
        if len(decisions) != 1 or decisions[0].status is not Status.VALID:
            raise PlanningConstructionError("VALIDATION_HISTORY_INVALID")
        validation = decisions[0]
    return PlanConstructionResult(attempt=attempt, validation=validation)
