"""D5 assessment is durable history, never execution authorization."""

from pathlib import Path

import pytest
from boberagent_contracts import AssetRef, ExecutionPlanV2, execution_intent_digest
from boberagent_contracts.plan_requirements import ExecutionLimits
from boberagent_contracts.plan_values import NetworkTarget
from boberagent_core import CoreDatabase
from boberagent_core.models import Asset
from boberagent_core.planning.construction import CoreExecutionPlanningService
from boberagent_core.planning.models import PlanPolicyDecision, PlanValidation
from boberagent_core.planning.policy_models import NarrowPolicyProfile
from boberagent_core.planning.policy_service import (
    CorePlanPolicyService,
    PolicyAssessmentError,
    PolicyProfileRegistry,
)
from boberagent_core.planning.records import PolicyDocument
from planning_construction_fixtures import prepared
from test_core_poc_acquisition import NOW


def _profile(
    plan: object, *, approval: bool = True, maximum: ExecutionLimits | None = None
) -> NarrowPolicyProfile:
    from boberagent_contracts import ExecutionPlanV2

    assert isinstance(plan, ExecutionPlanV2)
    assert isinstance(plan.target, NetworkTarget)
    return NarrowPolicyProfile(
        mission_ref=plan.mission_ref,
        allowed_asset_refs=(plan.target.asset_ref,),
        allowed_service_refs=(plan.target.service_ref,) if plan.target.service_ref else (),
        maximum_limits=maximum or plan.limits,
        require_operator_approval=approval,
    )


def _plan(database: CoreDatabase, tmp_path: Path) -> tuple[ExecutionPlanV2, PlanValidation]:
    _, request = prepared(database, tmp_path)
    result = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(request)
    plan = result.attempt.finalized_plan
    assert plan is not None and result.validation is not None
    return plan, result.validation


def test_policy_approval_reuse_reopen_and_no_execution(
    database: CoreDatabase, database_path: Path, tmp_path: Path
) -> None:
    plan, validation = _plan(database, tmp_path)
    profile = _profile(plan)
    service = CorePlanPolicyService(database, PolicyProfileRegistry((profile,)), clock=lambda: NOW)
    first = service.evaluate(plan.execution_plan_id)
    assert isinstance(first.record.document, PolicyDocument)
    assert first.record.document.value.decision is PlanPolicyDecision.REQUIRES_APPROVAL
    assert first.record.document.value.reason_codes == ("POLICY_APPROVAL_REQUIRED",)
    assert first.record.document.value.policy_sha256 == profile.digest
    assert first.record.document.value.intent_sha256 == execution_intent_digest(plan)
    assert first.record.context.validation_profile == validation.validation_profile
    assert first.authorization == "NONE" and first.execution_readiness == "NOT_ASSESSED"
    assert service.evaluate(plan.execution_plan_id) == first
    with database.unit_of_work() as work:
        assert len(work.plan_decisions.list_for_plan(plan.execution_plan_id)) == 2
        assert all(
            item.document.kind != "APPROVAL"
            for item in work.plan_decisions.list_for_plan(plan.execution_plan_id)
        )
    database.dispose()
    reopened = CoreDatabase(database.config)
    try:
        again = CorePlanPolicyService(
            reopened, PolicyProfileRegistry((profile,)), clock=lambda: NOW
        )
        assert again.evaluate(plan.execution_plan_id) == first
        assert again.get_assessment(first.record.decision_ref) == first
    finally:
        reopened.dispose()


def test_allow_is_assessment_only_and_scope_change_denies(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, _ = _plan(database, tmp_path)
    profile = _profile(plan, approval=False)
    service = CorePlanPolicyService(database, PolicyProfileRegistry((profile,)), clock=lambda: NOW)
    allowed = service.evaluate(plan.execution_plan_id)
    assert isinstance(allowed.record.document, PolicyDocument)
    assert allowed.record.document.value.decision is PlanPolicyDecision.ALLOW
    assert allowed.authorization == "NONE"
    with database.unit_of_work() as work:
        work.assets.add(
            Asset(
                asset_ref=AssetRef("asset-d5-new-scope"),
                mission_ref=plan.mission_ref,
                kind="host",
                primary_address="127.0.0.42",
                created_at=NOW,
            )
        )
    denied = service.evaluate(plan.execution_plan_id)
    assert isinstance(denied.record.document, PolicyDocument)
    assert denied.record.document.value.decision is PlanPolicyDecision.DENY
    assert "POLICY_SCOPE_CHANGED" in denied.record.document.value.reason_codes
    assert denied.record.decision_ref != allowed.record.decision_ref
    assert denied.record.context != allowed.record.context


def test_profile_scope_and_ceiling_deny_precede_approval(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, _ = _plan(database, tmp_path)
    smaller = plan.limits.model_copy(
        update={"wall_time_seconds": plan.limits.wall_time_seconds - 1}
    )
    profile = _profile(plan, maximum=smaller).model_copy(
        update={"allowed_asset_refs": (AssetRef("asset-other"),)}
    )
    result = CorePlanPolicyService(
        database, PolicyProfileRegistry((profile,)), clock=lambda: NOW
    ).evaluate(plan.execution_plan_id)
    assert isinstance(result.record.document, PolicyDocument)
    assert result.record.document.value.decision is PlanPolicyDecision.DENY
    assert "POLICY_TARGET_OUT_OF_SCOPE" in result.record.document.value.reason_codes
    assert "POLICY_LIMIT_EXCEEDED" in result.record.document.value.reason_codes


def test_unknown_profile_and_duplicate_configuration_fail_closed(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, _ = _plan(database, tmp_path)
    with pytest.raises(PolicyAssessmentError, match="POLICY_PROFILE_UNAVAILABLE"):
        CorePlanPolicyService(database, PolicyProfileRegistry(())).evaluate(plan.execution_plan_id)
    profile = _profile(plan)
    with pytest.raises(ValueError, match="POLICY_PROFILE_IDENTITY_CONFLICT"):
        PolicyProfileRegistry(
            (profile, profile.model_copy(update={"require_operator_approval": False}))
        )
    with database.unit_of_work() as work:
        assert len(work.plan_decisions.list_for_plan(plan.execution_plan_id)) == 1
