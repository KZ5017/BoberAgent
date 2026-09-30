"""D6 approval is a durable Core question and separate append-only decision."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from boberagent_contracts import AssetRef, InteractionLifecycle
from boberagent_core import CoreDatabase, DatabaseConfig, upgrade_database
from boberagent_core.interactions import InteractionConflict
from boberagent_core.models import Asset
from boberagent_core.planning.approval import CorePlanApprovalService, PlanApprovalError
from boberagent_core.planning.interaction_models import PlanningInteractionResponse
from boberagent_core.planning.models import PlanningAttemptLifecycle, PlanningInteractionPurpose
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.planning.records import ApprovalDocument
from test_core_poc_acquisition import NOW
from test_planning_policy import _plan, _profile


def _service(
    database: CoreDatabase, plan: object, *, approval: bool = True
) -> CorePlanApprovalService:
    policy = CorePlanPolicyService(
        database, PolicyProfileRegistry((_profile(plan, approval=approval),)), clock=lambda: NOW
    )
    return CorePlanApprovalService(database, policy, clock=lambda: NOW)


def _response(request: object, value: str) -> PlanningInteractionResponse:
    from boberagent_core.planning.interaction_models import PlanningInteractionRequest

    assert isinstance(request, PlanningInteractionRequest)
    return PlanningInteractionResponse(
        interaction_ref=request.interaction_ref,
        planning_attempt_ref=request.planning_attempt_ref,
        proposal_revision=request.proposal_revision,
        purpose=PlanningInteractionPurpose.POLICY_APPROVAL,
        operator_id="operator-test",
        value=value,
        responded_at=NOW,
    )


def test_approval_survives_restart_without_reopening_attempt(
    database: CoreDatabase, database_path: Path, tmp_path: Path
) -> None:
    plan, validation = _plan(database, tmp_path)
    service = _service(database, plan)
    pending = service.request(plan.execution_plan_id)
    assert pending.state is InteractionLifecycle.REQUESTED
    assert pending.request.policy_decision_ref is not None
    assert service.request(plan.execution_plan_id) == pending
    with database.unit_of_work() as work:
        attempt = work.planning_attempts.get(pending.request.planning_attempt_ref)
        assert attempt is not None and attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
        assert attempt.finalized_plan == plan
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(reopened)
        resumed = _service(reopened, plan)
        assert resumed.get(pending.request.interaction_ref) == pending
        approval = resumed.respond(_response(pending.request, "APPROVE"))
        assert isinstance(approval.document, ApprovalDocument)
        assert approval.document.value.decision == "APPROVE"
        assert approval.document.value.policy_decision_ref == pending.request.policy_decision_ref
        assert approval.document.value.validation_decision_ref is not None
        assert resumed.get_applicable_approval(plan.execution_plan_id) == approval
        assert resumed.respond(_response(pending.request, "APPROVE")) == approval
        answered = resumed.get(pending.request.interaction_ref)
        assert answered is not None and answered.state is InteractionLifecycle.ANSWERED
        with reopened.unit_of_work() as work:
            attempt = work.planning_attempts.get(pending.request.planning_attempt_ref)
            assert attempt is not None and attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
            assert len(work.plan_decisions.list_for_plan(plan.execution_plan_id)) == 3
        assert validation.status.value == "VALID"
    finally:
        reopened.dispose()


def test_denial_allow_and_conflicting_replay(database: CoreDatabase, tmp_path: Path) -> None:
    plan, _ = _plan(database, tmp_path)
    service = _service(database, plan)
    pending = service.request(plan.execution_plan_id)
    denied = service.respond(_response(pending.request, "DENY"))
    assert isinstance(denied.document, ApprovalDocument)
    assert denied.document.value.decision == "REJECT"
    assert service.get_applicable_approval(plan.execution_plan_id) is None
    with pytest.raises(InteractionConflict):
        service.respond(_response(pending.request, "APPROVE"))
    with pytest.raises(PlanApprovalError, match="POLICY_APPROVAL_NOT_REQUIRED"):
        _service(database, plan, approval=False).request(plan.execution_plan_id)


def test_hard_policy_deny_and_changed_scope_cannot_use_approval(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, _ = _plan(database, tmp_path)
    other = _profile(plan).model_copy(update={"allowed_asset_refs": (AssetRef("asset-other"),)})
    denied_policy = CorePlanPolicyService(
        database, PolicyProfileRegistry((other,)), clock=lambda: NOW
    )
    with pytest.raises(PlanApprovalError, match="POLICY_APPROVAL_NOT_REQUIRED"):
        CorePlanApprovalService(database, denied_policy, clock=lambda: NOW).request(
            plan.execution_plan_id
        )
    service = _service(database, plan)
    pending = service.request(plan.execution_plan_id)
    with database.unit_of_work() as work:
        work.assets.add(
            Asset(
                asset_ref=AssetRef("asset-approval-scope-change"),
                mission_ref=plan.mission_ref,
                kind="host",
                primary_address="127.0.0.222",
                created_at=NOW,
            )
        )
    with pytest.raises(PlanApprovalError, match="POLICY_ASSESSMENT_STALE"):
        service.respond(_response(pending.request, "APPROVE"))
    assert service.get_applicable_approval(plan.execution_plan_id) is None


def test_concurrent_approve_deny_has_one_authoritative_decision(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, _ = _plan(database, tmp_path)
    service = _service(database, plan)
    pending = service.request(plan.execution_plan_id)
    barrier = Barrier(2)

    def answer(choice: str) -> str:
        barrier.wait()
        try:
            record = service.respond(_response(pending.request, choice))
            assert isinstance(record.document, ApprovalDocument)
            return record.document.value.decision
        except InteractionConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(answer, "APPROVE")
        right = pool.submit(answer, "DENY")
        decisions = (left.result(), right.result())
    assert decisions.count("CONFLICT") == 1
    assert len([item for item in decisions if item in {"APPROVE", "REJECT"}]) == 1
    with database.unit_of_work() as work:
        approvals = tuple(
            row
            for row in work.plan_decisions.list_for_plan(plan.execution_plan_id)
            if isinstance(row.document, ApprovalDocument)
        )
    assert len(approvals) == 1
