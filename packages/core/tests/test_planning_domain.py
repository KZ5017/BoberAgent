"""D1 separates planning decisions and preserves immutable inspection authority."""

import pytest
from boberagent_contracts import CapabilityRunStatus, InteractionRef
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_values import (
    BindingProvenance,
    DeliveryChannel,
    OperatorValue,
    ParameterBinding,
    ResolutionState,
    ValueType,
)
from boberagent_core.inspections.classification_models import (
    ClassificationCoverage,
    ClassificationReason,
    ReasonCode,
    SupportClassification,
    SupportClassificationDocument,
)
from boberagent_core.inspections.identity import PoCInspectionRef
from boberagent_core.planning import (
    DecisionContext,
    InitialPlanPolicyProfile,
    OperatorPlanApproval,
    PlanningAnswer,
    PlanningAttempt,
    PlanningAttemptLifecycle,
    PlanningAttemptRef,
    PlanningDisposition,
    PlanningInspectionProvenance,
    PlanningRequest,
    PlanPolicyAssessment,
    PlanPolicyDecision,
    PlanProposal,
    PlanProposalRevision,
    PlanValidation,
    PlanValidationReason,
    PlanValidationReasonCode,
    PlanValidationStatus,
    decision_context_fingerprint,
    planning_request_fingerprint,
)
from boberagent_core.research.models import PoCCandidateRef, VulnerabilityHypothesisRef
from plan_test_fixtures import NOW, plan_fixture
from pydantic import TypeAdapter, ValidationError


def request_fixture(classification: SupportClassification) -> PlanningRequest:
    reasons = {
        SupportClassification.AUTOMATIC: (
            ReasonCode.SUPPORTED_ENTRYPOINT_UNAMBIGUOUS,
            ReasonCode.SUPPORTED_PROFILE_COVERAGE,
            ReasonCode.SUPPORTED_PYTHON_SINGLE_TARGET,
        ),
        SupportClassification.ASSISTED: (ReasonCode.REQUIRES_MANUAL_PARAMETER,),
        SupportClassification.UNSUPPORTED: (ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN,),
    }[classification]
    document = SupportClassificationDocument(
        semantic_inspection_ref=PoCInspectionRef("inspection-c2"),
        semantic_document_sha256="e" * 64,
        classification=classification,
        reasons=tuple(ClassificationReason(code=code, item_refs=("item-1",)) for code in reasons),
        coverage=ClassificationCoverage(
            material_paths=("check.py",), incomplete_material_paths=(), irrelevant_paths=()
        ),
        blocking_unknown_refs=("item-1",)
        if classification is SupportClassification.UNSUPPORTED
        else (),
    )
    plan = plan_fixture()
    return PlanningRequest(
        mission_ref=plan.mission_ref,
        hypothesis_ref=VulnerabilityHypothesisRef("hypothesis-d1"),
        candidate_ref=PoCCandidateRef("candidate-d1"),
        source=plan.source,
        inspection=PlanningInspectionProvenance(
            classification_ref=PoCInspectionRef("inspection-c3"),
            classification_sha256=canonical_digest(document),
            classification=document,
        ),
        proposal=PlanProposal(source=plan.source, target=plan.target, bindings=plan.bindings),
    )


def test_automatic_begins_planning_and_assisted_retains_unresolved_proposal() -> None:
    request = request_fixture(SupportClassification.AUTOMATIC)
    attempt = PlanningAttempt(
        planning_attempt_ref=PlanningAttemptRef("planning-1"),
        request=request,
        lifecycle=PlanningAttemptLifecycle.REQUESTED,
        created_at=NOW,
        updated_at=NOW,
    )
    assert attempt.finalized_plan is None and attempt.disposition is None
    data = request_fixture(SupportClassification.ASSISTED).model_dump()
    data["proposal"] = PlanProposal(
        source=request.source,
        unresolved_requirement_ids=("parameter-1",),
        bindings=(
            ParameterBinding(
                binding_id="parameter-1",
                parameter_id="mode",
                value_type=ValueType.TEXT,
                channel=DeliveryChannel.ARGUMENT,
                required=True,
                resolution=ResolutionState.UNRESOLVED,
                provenance=BindingProvenance(origin="PLANNING"),
            ),
        ),
    )
    assisted = PlanningAttempt(
        planning_attempt_ref=PlanningAttemptRef("planning-2"),
        request=PlanningRequest.model_validate(data),
        lifecycle=PlanningAttemptLifecycle.WAITING_INPUT,
        disposition=PlanningDisposition.REQUIRES_INPUT,
        created_at=NOW,
        updated_at=NOW,
    )
    assert assisted.finalized_plan is None
    assert assisted.request.proposal is not None
    assert assisted.request.proposal.bindings[0].value is None
    assert PlanningAttempt.model_validate_json(assisted.model_dump_json()) == assisted


def test_unsupported_preserves_exact_c3_blockers_and_forbids_finalized_intent() -> None:
    request = request_fixture(SupportClassification.UNSUPPORTED)
    attempt = PlanningAttempt(
        planning_attempt_ref=PlanningAttemptRef("planning-rejected"),
        request=request,
        lifecycle=PlanningAttemptLifecycle.COMPLETED,
        disposition=PlanningDisposition.UNSUPPORTED,
        created_at=NOW,
        updated_at=NOW,
    )
    assert attempt.request.inspection.classification == request.inspection.classification
    assert attempt.request.inspection.classification.blocking_unknown_refs == ("item-1",)
    assert attempt.finalized_plan is None
    for update in ({"finalized_plan": plan_fixture()}, {"disposition": "VALID"}):
        with pytest.raises(ValidationError, match="C3 UNSUPPORTED"):
            PlanningAttempt.model_validate({**attempt.model_dump(), **update})


def test_lifecycle_is_not_capability_run_lifecycle() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(PlanningAttemptLifecycle).validate_python(CapabilityRunStatus.RUNNING)
    request = request_fixture(SupportClassification.AUTOMATIC)
    data = {
        "planning_attempt_ref": "planning-1",
        "request": request,
        "lifecycle": "COMPLETED",
        "created_at": NOW,
        "updated_at": NOW,
    }
    with pytest.raises(ValidationError, match="explicit disposition"):
        PlanningAttempt.model_validate(data)
    with pytest.raises(ValidationError, match="finalized intent"):
        PlanningAttempt.model_validate({**data, "disposition": "VALID"})


def test_validation_policy_approval_remain_separate_non_authorizing_records() -> None:
    plan = plan_fixture()
    binding = {
        "execution_plan_ref": plan.execution_plan_id,
        "intent_sha256": canonical_digest(plan),
        "mission_ref": plan.mission_ref,
        "scope_sha256": "f" * 64,
    }
    validation = PlanValidation.model_validate(
        {
            **binding,
            "validation_profile": "m20-d-validation",
            "validation_version": "1",
            "status": "VALID",
            "assessed_at": NOW,
            "reasons": [PlanValidationReason(code=PlanValidationReasonCode.CONSISTENT_INTENT)],
        }
    )
    assessment = PlanPolicyAssessment.model_validate(
        {
            **binding,
            "policy_profile": "m20-python-single-target",
            "policy_version": "1",
            "decision": "ALLOW",
            "reason_codes": ["BOUNDED_INTENT"],
            "assessed_at": NOW,
        }
    )
    approval = OperatorPlanApproval.model_validate(
        {
            **binding,
            "policy_profile": "m20-python-single-target",
            "policy_version": "1",
            "decision": "APPROVE",
            "operator_id": "operator-test",
            "decided_at": NOW,
        }
    )
    assert validation.status is PlanValidationStatus.VALID
    assert assessment.decision is PlanPolicyDecision.ALLOW
    for record in (validation, assessment, approval):
        serialized = record.model_dump_json()
        assert "authorization" not in serialized and "token" not in serialized
        assert "node_id" not in serialized and "run_ref" not in serialized
        assert type(record).model_validate_json(serialized) == record
    with pytest.raises(ValidationError):
        PlanPolicyAssessment.model_validate(validation.model_dump())
    with pytest.raises(ValidationError):
        OperatorPlanApproval.model_validate(assessment.model_dump())


def test_narrow_initial_policy_profile_cannot_be_relaxed_by_caller() -> None:
    profile = InitialPlanPolicyProfile(maximum_limits=plan_fixture().limits)
    for update in (
        {"user_space": False},
        {"runtime_kind": "powershell"},
        {"execution_location": "TARGET"},
        {"critical_unknowns_allowed": True},
        {"broad_effects_allowed": True},
        {"allowed_target_roles": ["DIRECTORY"]},
        {"allow_arbitrary_network": True},
    ):
        with pytest.raises(ValidationError):
            InitialPlanPolicyProfile.model_validate({**profile.model_dump(), **update})
    assert InitialPlanPolicyProfile.model_validate_json(profile.model_dump_json()) == profile


def test_planning_and_decision_context_fingerprints_are_distinct_and_sensitive_to_inputs() -> None:
    request = request_fixture(SupportClassification.AUTOMATIC)
    assert planning_request_fingerprint(request) == planning_request_fingerprint(
        PlanningRequest.model_validate_json(request.model_dump_json())
    )
    data = request.model_dump()
    data["proposal"] = PlanProposal(source=request.source, unresolved_requirement_ids=("timeout",))
    assert planning_request_fingerprint(
        PlanningRequest.model_validate(data)
    ) != planning_request_fingerprint(request)
    context = DecisionContext(
        mission_ref=request.mission_ref,
        intent_sha256="a" * 64,
        scope_sha256="b" * 64,
        classification_sha256=request.inspection.classification_sha256,
        validation_profile="m20-d-validation",
        validation_version="1",
        policy=InitialPlanPolicyProfile(maximum_limits=plan_fixture().limits),
    )
    assert decision_context_fingerprint(context) != planning_request_fingerprint(request)
    changed = DecisionContext.model_validate({**context.model_dump(), "scope_sha256": "c" * 64})
    assert decision_context_fingerprint(changed) != decision_context_fingerprint(context)


def test_revision_and_answer_provenance_without_current_hitl_behavior() -> None:
    request = request_fixture(SupportClassification.ASSISTED)
    answer = PlanningAnswer(
        answer_id="answer-1",
        interaction_ref=InteractionRef("interaction-1"),
        planning_attempt_ref=PlanningAttemptRef("planning-1"),
        parameter_id="mode",
        operator_id="operator-1",
        value=OperatorValue(answer_id="answer-1", value="check"),
        answered_at=NOW,
    )
    assert request.proposal is not None
    revision = PlanProposalRevision(
        planning_attempt_ref=answer.planning_attempt_ref,
        revision_number=1,
        proposal=request.proposal,
        answers=(answer,),
        created_at=NOW,
    )
    assert PlanProposalRevision.model_validate_json(revision.model_dump_json()) == revision
    assert revision.answers[0].interaction_ref == answer.interaction_ref
    with pytest.raises(ValidationError, match="another PlanningAttempt"):
        PlanProposalRevision.model_validate(
            {**revision.model_dump(), "planning_attempt_ref": "planning-other"}
        )
    with pytest.raises(ValidationError, match="previous revision"):
        PlanProposalRevision.model_validate({**revision.model_dump(), "revision_number": 2})
    with pytest.raises(ValidationError, match="frozen_instance"):
        revision.proposal.source = request.source
