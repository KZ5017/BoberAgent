"""Offline D7 acceptance over real D3-D6 services and migration-backed Core state.

Synthetic upstream fixture helpers prepare the retained C1/C2/C3 records. No acquired
source is executed, and no planning decision is reimplemented here.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import pytest
from boberagent_contracts import AssetRef, ExecutionPlanRef, execution_intent_digest
from boberagent_core import Asset, CoreDatabase, DatabaseConfig, upgrade_database
from boberagent_core.inspections.models import PoCInspection
from boberagent_core.inspections.semantic_models import SemanticInspectionDocument
from boberagent_core.interactions.errors import InteractionConflict
from boberagent_core.planning.admission import CorePlanningAdmissionService
from boberagent_core.planning.admission_models import PlanningAdmissionOutcome
from boberagent_core.planning.approval import CorePlanApprovalService, PlanApprovalError
from boberagent_core.planning.assistance import CorePlanningAssistanceService
from boberagent_core.planning.construction import CoreExecutionPlanningService
from boberagent_core.planning.fingerprints import decision_context_fingerprint
from boberagent_core.planning.interaction_models import (
    PlanningInteractionRequest,
    PlanningInteractionResponse,
)
from boberagent_core.planning.models import (
    PlanningAttemptLifecycle,
    PlanningDisposition,
    PlanningInteractionPurpose,
    PlanPolicyDecision,
    PlanValidationStatus,
)
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.planning.records import ApprovalDocument, PolicyDocument, ValidationDocument
from planning_admission_fixtures import seed_chain
from planning_construction_fixtures import CHECKER, prepared
from sqlalchemy import text
from test_core_poc_acquisition import NOW
from test_planning_policy import _profile

CaseName = Literal[
    "automatic_allow",
    "assisted_entrypoint",
    "approval_approve",
    "approval_deny",
    "hard_policy_deny",
    "material_unknown",
]
CASES: tuple[CaseName, ...] = (
    "automatic_allow",
    "assisted_entrypoint",
    "approval_approve",
    "approval_deny",
    "hard_policy_deny",
    "material_unknown",
)
_NO_EXECUTION_TABLES = (
    "capability_runs",
    "capability_routing_decisions",
    "transport_inbox",
    "result_ingestions",
    "artifacts",
    "secret_access_records",
    "workflow_runs",
    "workflow_step_runs",
)


@dataclass(frozen=True)
class CaseReport:
    case: CaseName
    mission_ref: str
    planning_attempt_ref: str
    admission: str
    proposal_revisions: int
    planning_interaction_ref: str | None = None
    policy_interaction_ref: str | None = None
    execution_plan_ref: str | None = None
    intent_sha256: str | None = None
    validation_decision_ref: str | None = None
    policy_decision_ref: str | None = None
    policy_context_fingerprint: str | None = None
    operator_approval_decision_ref: str | None = None
    policy_result: str | None = None
    authorization: str = "NONE"
    readiness: str = "NOT_ASSESSED"

    def safe_output(self) -> dict[str, str | int | None]:
        return asdict(self)


def _open(root: Path) -> CoreDatabase:
    root.mkdir(parents=True, exist_ok=True)
    database = CoreDatabase(DatabaseConfig.sqlite(root / "core.sqlite3"))
    upgrade_database(database)
    return database


def _reopen(database: CoreDatabase) -> CoreDatabase:
    config = database.config
    database.dispose()
    reopened = CoreDatabase(config)
    upgrade_database(reopened)
    return reopened


def _counts(database: CoreDatabase) -> dict[str, int]:
    # These read-only assertions are acceptance instrumentation, not application APIs.
    with database._migration_engine.connect() as connection:
        return {
            name: int(connection.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one())
            for name in _NO_EXECUTION_TABLES
        }


def _upstream_unchanged(database: CoreDatabase, c2: PoCInspection, c3: PoCInspection) -> None:
    with database.unit_of_work() as work:
        assert work.inspections.get(c2.inspection_ref) == c2
        assert work.inspections.get(c3.inspection_ref) == c3


def _validation_ref(database: CoreDatabase, plan_ref: ExecutionPlanRef) -> str:
    with database.unit_of_work() as work:
        records = tuple(
            item
            for item in work.plan_decisions.list_for_plan(plan_ref)
            if isinstance(item.document, ValidationDocument)
        )
    assert len(records) == 1
    assert isinstance(records[0].document, ValidationDocument)
    assert records[0].document.value.status is PlanValidationStatus.VALID
    return str(records[0].decision_ref)


def _answer(request: PlanningInteractionRequest, value: str) -> PlanningInteractionResponse:
    return PlanningInteractionResponse(
        interaction_ref=request.interaction_ref,
        planning_attempt_ref=request.planning_attempt_ref,
        proposal_revision=request.proposal_revision,
        purpose=request.purpose,
        operator_id="d7-operator",
        value=value,
        responded_at=NOW,
    )


def _automatic(root: Path) -> CaseReport:
    database = _open(root)
    try:
        chain, request = prepared(database, root)
        admission_service = CorePlanningAdmissionService(database, clock=lambda: NOW)
        admitted = admission_service.get_admission(request.planning_attempt_ref)
        assert admitted is not None
        assert admitted.outcome is PlanningAdmissionOutcome.ELIGIBLE_AUTOMATIC
        baseline = _counts(database)
        database = _reopen(database)  # checkpoint A: admitted but not constructed
        admission_service = CorePlanningAdmissionService(database, clock=lambda: NOW)
        assert admission_service.admit(chain.request) == admitted
        planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
        constructed = planner.construct(request)
        plan = constructed.attempt.finalized_plan
        assert plan is not None and constructed.validation is not None
        assert constructed.attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
        assert constructed.attempt.disposition is PlanningDisposition.VALID
        assert constructed.attempt.revisions and len(constructed.attempt.revisions) == 1
        assert constructed.validation.intent_sha256 == execution_intent_digest(plan)
        database = _reopen(database)  # checkpoint C: immutable plan + validation
        planner = CoreExecutionPlanningService(database, clock=lambda: NOW)
        assert planner.get(request.planning_attempt_ref) == constructed
        assert planner.construct(request) == constructed
        profile = _profile(plan, approval=False)
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((profile,)), clock=lambda: NOW
        )
        allowed = policy.evaluate(plan.execution_plan_id)
        assert isinstance(allowed.record.document, PolicyDocument)
        assert allowed.record.document.value.decision is PlanPolicyDecision.ALLOW
        assert allowed.authorization == "NONE" and allowed.execution_readiness == "NOT_ASSESSED"
        assert policy.evaluate(plan.execution_plan_id) == allowed
        assert (
            CorePlanApprovalService(database, policy, clock=lambda: NOW).get_applicable_approval(
                plan.execution_plan_id
            )
            is None
        )
        database = _reopen(database)
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((profile,)), clock=lambda: NOW
        )
        assert policy.evaluate(plan.execution_plan_id) == allowed
        _upstream_unchanged(database, chain.c2, chain.c3)
        assert _counts(database) == baseline
        return CaseReport(
            case="automatic_allow",
            mission_ref=str(chain.request.mission_ref),
            planning_attempt_ref=str(request.planning_attempt_ref),
            admission=admitted.outcome.value,
            proposal_revisions=len(constructed.attempt.revisions),
            execution_plan_ref=str(plan.execution_plan_id),
            intent_sha256=execution_intent_digest(plan),
            validation_decision_ref=_validation_ref(database, plan.execution_plan_id),
            policy_decision_ref=str(allowed.record.decision_ref),
            policy_context_fingerprint=decision_context_fingerprint(allowed.record.context),
            policy_result=allowed.record.document.value.decision.value,
        )
    finally:
        database.dispose()


def _assisted(root: Path) -> CaseReport:
    database = _open(root)
    try:
        chain, request = prepared(database, root, {"checker.py": CHECKER, "other.py": CHECKER})
        admission = CorePlanningAdmissionService(database, clock=lambda: NOW).get_admission(
            request.planning_attempt_ref
        )
        assert admission is not None
        assert admission.outcome is PlanningAdmissionOutcome.ELIGIBLE_ASSISTED
        baseline = _counts(database)
        waiting = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
        assert waiting.attempt.lifecycle is PlanningAttemptLifecycle.WAITING_INPUT
        assert waiting.attempt.disposition is PlanningDisposition.REQUIRES_INPUT
        assistance = CorePlanningAssistanceService(database, clock=lambda: NOW)
        pending = assistance.pending(request.planning_attempt_ref)
        assert len(pending) == 1
        question = pending[0].request
        assert question.purpose is PlanningInteractionPurpose.PLANNING_ENTRYPOINT_SELECTION
        database = _reopen(database)  # checkpoint B: WAITING_INPUT + pending question
        assistance = CorePlanningAssistanceService(database, clock=lambda: NOW)
        assert assistance.pending(request.planning_attempt_ref) == pending
        assert isinstance(chain.c2.document, SemanticInspectionDocument)
        candidates = chain.c2.document.entrypoint_candidates
        selected = next(item.item_id for item in candidates if item.source_path == "checker.py")
        assert selected in {option.option_id for option in question.options}
        selected_gaps = tuple(
            item for item in chain.c2.document.unknowns if item.source_path == "checker.py"
        )
        assert len(selected_gaps) == 1
        assert selected_gaps[0].reason == "MULTIPLE_ENTRYPOINT_CANDIDATES"
        stale = _answer(question, selected).model_copy(
            update={"proposal_revision": question.proposal_revision + 1}
        )
        with pytest.raises(InteractionConflict):
            assistance.respond(stale)
        response = _answer(question, selected)
        accepted = assistance.respond(response)
        assert assistance.respond(response) == accepted
        other = next(
            option.option_id for option in question.options if option.option_id != selected
        )
        with pytest.raises(InteractionConflict):
            assistance.respond(_answer(question, other))
        constructed = assistance.resume(request.planning_attempt_ref)
        plan = constructed.attempt.finalized_plan
        assert plan is not None and constructed.validation is not None
        assert constructed.attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
        assert constructed.attempt.disposition is PlanningDisposition.VALID
        assert len(constructed.attempt.revisions) == 3
        assert (
            constructed.attempt.revisions[1].answers[0].interaction_ref == question.interaction_ref
        )
        assert plan.entrypoint.evidence_ids == (selected,)
        database = _reopen(database)
        assert (
            CoreExecutionPlanningService(database).get(request.planning_attempt_ref) == constructed
        )
        _upstream_unchanged(database, chain.c2, chain.c3)
        assert _counts(database) == baseline
        return CaseReport(
            case="assisted_entrypoint",
            mission_ref=str(chain.request.mission_ref),
            planning_attempt_ref=str(request.planning_attempt_ref),
            admission=admission.outcome.value,
            proposal_revisions=len(constructed.attempt.revisions),
            planning_interaction_ref=str(question.interaction_ref),
            execution_plan_ref=str(plan.execution_plan_id),
            intent_sha256=execution_intent_digest(plan),
            validation_decision_ref=_validation_ref(database, plan.execution_plan_id),
        )
    finally:
        database.dispose()


def _approval(root: Path, choice: Literal["APPROVE", "DENY"]) -> CaseReport:
    database = _open(root)
    try:
        chain, request = prepared(database, root)
        admission = CorePlanningAdmissionService(database).get_admission(
            request.planning_attempt_ref
        )
        assert admission is not None
        baseline = _counts(database)
        constructed = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
        plan = constructed.attempt.finalized_plan
        assert plan is not None and constructed.validation is not None
        profile = _profile(plan, approval=True)
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((profile,)), clock=lambda: NOW
        )
        assessment = policy.evaluate(plan.execution_plan_id)
        assert isinstance(assessment.record.document, PolicyDocument)
        assert assessment.record.document.value.decision is PlanPolicyDecision.REQUIRES_APPROVAL
        assert assessment.authorization == "NONE"
        assert assessment.execution_readiness == "NOT_ASSESSED"
        approval = CorePlanApprovalService(database, policy, clock=lambda: NOW)
        pending = approval.request(plan.execution_plan_id)
        assert pending.request.purpose is PlanningInteractionPurpose.POLICY_APPROVAL
        assert approval.request(plan.execution_plan_id) == pending
        database = _reopen(database)  # checkpoint D: terminal Attempt + pending approval
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((profile,)), clock=lambda: NOW
        )
        approval = CorePlanApprovalService(database, policy, clock=lambda: NOW)
        assert approval.get(pending.request.interaction_ref) == pending
        with database.unit_of_work() as work:
            attempt = work.planning_attempts.get(request.planning_attempt_ref)
            assert attempt is not None
            assert attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
            assert attempt.disposition is PlanningDisposition.VALID
            assert attempt.finalized_plan == plan
        response = _answer(pending.request, choice)
        decision = approval.respond(response)
        assert isinstance(decision.document, ApprovalDocument)
        assert decision.document.value.decision == ("APPROVE" if choice == "APPROVE" else "REJECT")
        assert approval.respond(response) == decision
        if choice == "APPROVE":
            with pytest.raises(InteractionConflict):
                approval.respond(_answer(pending.request, "DENY"))
            assert approval.get_applicable_approval(plan.execution_plan_id) == decision
        else:
            assert approval.get_applicable_approval(plan.execution_plan_id) is None
        database = _reopen(database)  # checkpoint E: append-only operator decision
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((profile,)), clock=lambda: NOW
        )
        approval = CorePlanApprovalService(database, policy, clock=lambda: NOW)
        assert policy.evaluate(plan.execution_plan_id) == assessment
        assert approval.get(pending.request.interaction_ref) is not None
        assert (
            approval.get_applicable_approval(plan.execution_plan_id) == decision
            if choice == "APPROVE"
            else approval.get_applicable_approval(plan.execution_plan_id) is None
        )
        with database.unit_of_work() as work:
            assert work.execution_plans.get(plan.execution_plan_id) is not None
            decisions = work.plan_decisions.list_for_plan(plan.execution_plan_id)
            assert len(decisions) == 3
            assert decision in decisions and assessment.record in decisions
            attempt = work.planning_attempts.get(request.planning_attempt_ref)
            assert attempt is not None and attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
        if choice == "APPROVE":
            with database.unit_of_work() as work:
                work.assets.add(
                    Asset(
                        asset_ref=AssetRef("asset-d7-context-change"),
                        mission_ref=plan.mission_ref,
                        kind="host",
                        primary_address="192.0.2.44",
                        created_at=NOW,
                    )
                )
            changed = policy.evaluate(plan.execution_plan_id)
            assert changed.record.decision_ref != assessment.record.decision_ref
            assert decision_context_fingerprint(changed.record.context) != (
                decision_context_fingerprint(assessment.record.context)
            )
            assert approval.get_applicable_approval(plan.execution_plan_id) is None
            with database.unit_of_work() as work:
                assert decision in work.plan_decisions.list_for_plan(plan.execution_plan_id)
        _upstream_unchanged(database, chain.c2, chain.c3)
        assert _counts(database) == baseline
        return CaseReport(
            case="approval_approve" if choice == "APPROVE" else "approval_deny",
            mission_ref=str(chain.request.mission_ref),
            planning_attempt_ref=str(request.planning_attempt_ref),
            admission=admission.outcome.value,
            proposal_revisions=len(constructed.attempt.revisions),
            policy_interaction_ref=str(pending.request.interaction_ref),
            execution_plan_ref=str(plan.execution_plan_id),
            intent_sha256=execution_intent_digest(plan),
            validation_decision_ref=_validation_ref(database, plan.execution_plan_id),
            policy_decision_ref=str(assessment.record.decision_ref),
            policy_context_fingerprint=decision_context_fingerprint(assessment.record.context),
            operator_approval_decision_ref=str(decision.decision_ref),
            policy_result=assessment.record.document.value.decision.value,
        )
    finally:
        database.dispose()


def _hard_deny(root: Path) -> CaseReport:
    database = _open(root)
    try:
        chain, request = prepared(database, root)
        baseline = _counts(database)
        constructed = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
        plan = constructed.attempt.finalized_plan
        assert plan is not None and constructed.validation is not None
        smaller = plan.limits.model_copy(
            update={"wall_time_seconds": plan.limits.wall_time_seconds - 1}
        )
        profile = _profile(plan, approval=True, maximum=smaller)
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((profile,)), clock=lambda: NOW
        )
        denied = policy.evaluate(plan.execution_plan_id)
        assert isinstance(denied.record.document, PolicyDocument)
        assert denied.record.document.value.decision is PlanPolicyDecision.DENY
        assert "POLICY_LIMIT_EXCEEDED" in denied.record.document.value.reason_codes
        with pytest.raises(PlanApprovalError, match="POLICY_APPROVAL_NOT_REQUIRED"):
            CorePlanApprovalService(database, policy, clock=lambda: NOW).request(
                plan.execution_plan_id
            )
        with database.unit_of_work() as work:
            assert work.planning_interactions.list_pending(request.planning_attempt_ref) == ()
            assert len(work.plan_decisions.list_for_plan(plan.execution_plan_id)) == 2
        assert denied.authorization == "NONE" and denied.execution_readiness == "NOT_ASSESSED"
        _upstream_unchanged(database, chain.c2, chain.c3)
        assert _counts(database) == baseline
        return CaseReport(
            case="hard_policy_deny",
            mission_ref=str(chain.request.mission_ref),
            planning_attempt_ref=str(request.planning_attempt_ref),
            admission=PlanningAdmissionOutcome.ELIGIBLE_AUTOMATIC.value,
            proposal_revisions=1,
            execution_plan_ref=str(plan.execution_plan_id),
            intent_sha256=execution_intent_digest(plan),
            validation_decision_ref=_validation_ref(database, plan.execution_plan_id),
            policy_decision_ref=str(denied.record.decision_ref),
            policy_context_fingerprint=decision_context_fingerprint(denied.record.context),
            policy_result=denied.record.document.value.decision.value,
        )
    finally:
        database.dispose()


def _material_unknown(root: Path) -> CaseReport:
    database = _open(root)
    try:
        chain = seed_chain(
            database,
            root,
            {
                "checker.py": CHECKER + b"\nunknown.connect()\n",
                "helper.bin": b"\x00\xff",
                "README.md": b"No credentials required.\n",
            },
        )
        baseline = _counts(database)
        admission = CorePlanningAdmissionService(database, clock=lambda: NOW).admit(chain.request)
        assert admission.outcome is PlanningAdmissionOutcome.REJECTED_UNSUPPORTED
        assert admission.attempt.disposition is PlanningDisposition.UNSUPPORTED
        assert admission.attempt.finalized_plan is None
        assert admission.attempt.request.inspection.classification.blocking_unknown_refs
        assert (
            CorePlanningAssistanceService(database).pending(admission.attempt.planning_attempt_ref)
            == ()
        )
        with database.unit_of_work() as work:
            assert (
                work.execution_plans.get_by_attempt(admission.attempt.planning_attempt_ref) is None
            )
        database = _reopen(database)
        assert CorePlanningAdmissionService(database).admit(chain.request) == admission
        _upstream_unchanged(database, chain.c2, chain.c3)
        assert _counts(database) == baseline
        return CaseReport(
            case="material_unknown",
            mission_ref=str(chain.request.mission_ref),
            planning_attempt_ref=str(admission.attempt.planning_attempt_ref),
            admission=admission.outcome.value,
            proposal_revisions=0,
            policy_result="NOT_EVALUATED",
        )
    finally:
        database.dispose()


def run_case(case: CaseName, root: Path) -> CaseReport:
    if case == "automatic_allow":
        return _automatic(root)
    if case == "assisted_entrypoint":
        return _assisted(root)
    if case == "approval_approve":
        return _approval(root, "APPROVE")
    if case == "approval_deny":
        return _approval(root, "DENY")
    if case == "hard_policy_deny":
        return _hard_deny(root)
    return _material_unknown(root)


def run_all(root: Path) -> tuple[CaseReport, ...]:
    return tuple(run_case(case, root / case) for case in CASES)
