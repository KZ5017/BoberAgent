"""Core-only E2 preparation admission from current D history and metadata.

This service issues a historical preparation-only permit claim. It never creates a
CapabilityRun, sends a transport message, opens source bytes, or grants execution.
"""

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from boberagent_contracts import (
    CapabilityRunRef,
    PreparationPermit,
    PreparationPermitRef,
    RuntimePreparationRef,
    RuntimePreparationSpec,
)
from boberagent_contracts.execution_plan_v2 import ExecutionPlanV2
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_requirements import (
    ExecutionLocation,
    NetworkDestinationClass,
    PlanDependencyKind,
)
from boberagent_contracts.runtime_preparation import (
    ConfinementFeature,
    ConfinementRequirement,
    PreparationAuthorityBoundary,
    PreparationSource,
    initial_python_preparation_profile,
    preparation_profile_digest,
    preparation_spec_fingerprint,
)
from pydantic import ValidationError

from boberagent_core.capabilities import CapabilityRegistry
from boberagent_core.capabilities.models import ProviderAvailability
from boberagent_core.clock import utc_now
from boberagent_core.persistence import CoreDatabase
from boberagent_core.persistence.repositories import CoreUnitOfWork
from boberagent_core.planning.admission import _authoritative_request
from boberagent_core.planning.admission_errors import PlanningAdmissionError
from boberagent_core.planning.admission_models import PlanningAdmissionRequest
from boberagent_core.planning.approval import CorePlanApprovalService, PlanApprovalError
from boberagent_core.planning.fingerprints import decision_context_fingerprint
from boberagent_core.planning.models import (
    PlanningAttemptLifecycle,
    PlanningDisposition,
    PlanPolicyDecision,
    PlanValidationStatus,
)
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyAssessmentError
from boberagent_core.planning.records import ApprovalDocument, PolicyDocument, ValidationDocument

from .models import (
    PreparationAdmission,
    PreparationAttempt,
    PreparationContext,
    PreparationDisposition,
    PreparationLifecycle,
    PreparationRequest,
)
from .models import (
    PreparationAdmissionReason as Reason,
)


class PreparationAdmissionError(ValueError):
    """Invalid request identity or unavailable authoritative plan; never source text."""


class CoreRuntimePreparationAdmissionService:
    """Explicit metadata-only pump; no E3 transport or Node authority."""

    def __init__(
        self,
        database: CoreDatabase,
        policy: CorePlanPolicyService,
        approval: CorePlanApprovalService,
        registry: CapabilityRegistry,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._policy = policy
        self._approval = approval
        self._registry = registry
        self._clock = clock

    def admit(self, request: PreparationRequest) -> PreparationAdmission:
        request = _strict_request(request)
        now = self._now()
        with self._database.unit_of_work() as work:
            context, reason, plan = self._assess(work, request)
            fingerprint = canonical_digest(context)
            existing = work.runtime_preparations.find_by_fingerprint(fingerprint)
            if existing is not None:
                permit = (
                    work.runtime_preparations.get_permit(existing.permit_ref)
                    if existing.permit_ref is not None
                    else None
                )
                return PreparationAdmission(
                    attempt=existing,
                    permit=permit,
                    current_applicable=(
                        reason is None
                        and existing.lifecycle is PreparationLifecycle.REQUESTED
                        and permit is not None
                        and now < permit.expires_at
                    ),
                    current_reason=reason or existing.reason_code,
                )
            preparation_ref = RuntimePreparationRef(f"preparation-{uuid4().hex}")
            run_ref = (
                None if reason is not None else CapabilityRunRef(f"run-preparation-{uuid4().hex}")
            )
            permit_ref = (
                None
                if reason is not None
                else PreparationPermitRef(f"preparation-permit-{uuid4().hex}")
            )
            spec = None if reason is not None else self._spec(preparation_ref, context, plan)
            # Strict E1 decoding can still reject a plan/config combination that D accepts.
            # Preserve it as an E-only rejection, not a fake Node failure.
            if reason is None and spec is None:
                reason = Reason.PREPARATION_PROFILE_UNSUPPORTED
                run_ref = None
                permit_ref = None
            permit = (
                None
                if reason is not None or spec is None or run_ref is None or permit_ref is None
                else PreparationPermit(
                    schema_version="preparation-permit-v1",
                    permit_ref=permit_ref,
                    spec=spec,
                    spec_sha256=preparation_spec_fingerprint(spec),
                    run_ref=run_ref,
                    validation_decision_ref=_required(context.validation_decision_ref),
                    validation_sha256=_required(context.validation_sha256),
                    policy_decision_ref=_required(context.policy_decision_ref),
                    policy_context_sha256=_required(context.policy_context_sha256),
                    policy_decision=_policy_decision(context.policy_decision),
                    approval_decision_ref=context.approval_decision_ref,
                    issued_at=now,
                    not_before=now,
                    expires_at=now + timedelta(minutes=15),
                    admission_nonce=f"preparation-{uuid4().hex}",
                    maximum_preparation_runs=1,
                    boundary=PreparationAuthorityBoundary(),
                )
            )
            attempt = PreparationAttempt(
                preparation_ref=preparation_ref,
                context=context,
                request_fingerprint=fingerprint,
                lifecycle=(
                    PreparationLifecycle.REQUESTED
                    if reason is None
                    else PreparationLifecycle.REJECTED
                ),
                disposition=(
                    PreparationDisposition.ELIGIBLE
                    if reason is None
                    else PreparationDisposition.REJECTED
                ),
                reason_code=reason,
                reserved_run_ref=run_ref,
                spec=spec,
                permit_ref=permit_ref,
                revision=0,
                created_at=now,
                updated_at=now,
                terminal_at=now if reason is not None else None,
            )
            stored, historical = work.runtime_preparations.add(attempt, permit)
            return PreparationAdmission(
                attempt=stored,
                permit=historical,
                current_applicable=(
                    reason is None
                    and stored.lifecycle is PreparationLifecycle.REQUESTED
                    and historical is not None
                    and now < historical.expires_at
                ),
                current_reason=reason or stored.reason_code,
            )

    def get_attempt(self, ref: RuntimePreparationRef) -> PreparationAttempt | None:
        with self._database.unit_of_work() as work:
            return work.runtime_preparations.get(ref)

    def get_permit(self, ref: PreparationPermitRef) -> PreparationPermit | None:
        """Historical permit lookup, not a current dispatch authorization."""
        with self._database.unit_of_work() as work:
            return work.runtime_preparations.get_permit(ref)

    def current_admission(self, ref: RuntimePreparationRef) -> PreparationAdmission | None:
        """Read-only E2 applicability; E3 must recheck immediately before side effects."""
        with self._database.unit_of_work() as work:
            attempt = work.runtime_preparations.get(ref)
            if attempt is None:
                return None
            permit = (
                work.runtime_preparations.get_permit(attempt.permit_ref)
                if attempt.permit_ref is not None
                else None
            )
            try:
                current, reason, _plan = self._assess(work, attempt.context.request)
            except PreparationAdmissionError:
                current, reason = None, Reason.PLAN_INVALID_OR_STALE
            if current != attempt.context or reason is not None:
                return PreparationAdmission(
                    attempt=attempt,
                    permit=permit,
                    current_applicable=False,
                    current_reason=reason or Reason.PLAN_INVALID_OR_STALE,
                )
            if permit is not None and not permit.not_before <= self._now() < permit.expires_at:
                return PreparationAdmission(
                    attempt=attempt,
                    permit=permit,
                    current_applicable=False,
                    current_reason=Reason.PLAN_INVALID_OR_STALE,
                )
            return PreparationAdmission(
                attempt=attempt,
                permit=permit,
                current_applicable=attempt.lifecycle is PreparationLifecycle.REQUESTED,
                current_reason=attempt.reason_code,
            )

    def _assess(
        self, work: CoreUnitOfWork, request: PreparationRequest
    ) -> tuple[PreparationContext, Reason | None, ExecutionPlanV2]:
        stored = work.execution_plans.get(request.plan_ref)
        if stored is None:
            raise PreparationAdmissionError("PLAN_NOT_FOUND")
        plan = stored.plan
        attempt = work.planning_attempts.get(stored.planning_attempt_ref)
        if attempt is None or plan.mission_ref != request.mission_ref:
            raise PreparationAdmissionError("PLAN_MISSION_MISMATCH")
        inspection = attempt.request.inspection
        source = plan.source
        records = work.plan_decisions.list_for_plan(request.plan_ref)
        validations = tuple(
            item
            for item in records
            if isinstance(item.document, ValidationDocument)
            and item.document.value.status is PlanValidationStatus.VALID
            and item.document.value.execution_plan_ref == request.plan_ref
            and item.document.value.intent_sha256 == stored.intent_sha256
            and (item.document.value.validation_profile, item.document.value.validation_version)
            == ("m20-d4-plan-validator", "1")
        )
        validation = validations[0] if len(validations) == 1 else None
        policy = None
        with suppress(PolicyAssessmentError):
            policy = self._policy.current_assessment(request.plan_ref)
        # Missing trusted current composition is not historical ALLOW authority.
        policy_record = None if policy is None else policy.record
        policy_value = (
            policy_record.document.value
            if policy_record is not None and isinstance(policy_record.document, PolicyDocument)
            else None
        )
        approval = None
        if (
            policy_value is not None
            and policy_value.decision is PlanPolicyDecision.REQUIRES_APPROVAL
        ):
            with suppress(PlanApprovalError):
                approval = self._approval.get_applicable_approval(request.plan_ref)
            if approval is not None and (
                not isinstance(approval.document, ApprovalDocument)
                or policy_record is None
                or approval.document.value.policy_decision_ref != policy_record.decision_ref
                or approval.document.value.validation_decision_ref
                != (None if validation is None else validation.decision_ref)
                or approval.document.value.policy_context_fingerprint
                != decision_context_fingerprint(policy_record.context)
            ):
                approval = None
        provider = self._registry.get_provider(request.provider_id)
        baseline = initial_python_preparation_profile()
        manifest_record = work.artifacts.get_record(source.manifest_artifact_ref)
        context = PreparationContext(
            request=request,
            planning_attempt_ref=stored.planning_attempt_ref,
            plan_intent_sha256=stored.intent_sha256,
            source=source,
            semantic_inspection_ref=inspection.classification.semantic_inspection_ref,
            semantic_sha256=inspection.classification.semantic_document_sha256,
            classification_inspection_ref=inspection.classification_ref,
            classification_sha256=inspection.classification_sha256,
            validation_decision_ref=None if validation is None else validation.decision_ref,
            validation_sha256=(
                None if validation is None else canonical_digest(validation.document.value)
            ),
            policy_decision_ref=None if policy_record is None else policy_record.decision_ref,
            policy_context_sha256=(
                None
                if policy_record is None
                else decision_context_fingerprint(policy_record.context)
            ),
            policy_sha256=None if policy is None else policy.policy_sha256,
            policy_decision=None if policy_value is None else policy_value.decision,
            approval_decision_ref=None if approval is None else approval.decision_ref,
            provider_version=None if provider is None else provider.implementation_version,
            provider_availability=None if provider is None else provider.availability,
            provider_node_lifecycle=None if provider is None else provider.node_lifecycle,
            profile_sha256=preparation_profile_digest(baseline),
            manifest_size_bytes=(
                None if manifest_record is None else manifest_record.descriptor.size_bytes
            ),
        )
        reason = self._reason(
            work, request, context, plan, attempt, validation, policy_value, provider
        )
        return context, reason, plan

    def _reason(
        self,
        work: CoreUnitOfWork,
        request: PreparationRequest,
        context: PreparationContext,
        plan: ExecutionPlanV2,
        attempt: object,
        validation: object,
        policy: object,
        provider: object,
    ) -> Reason | None:
        from boberagent_core.capabilities.models import CapabilityProvider
        from boberagent_core.planning.models import PlanningAttempt, PlanPolicyAssessment

        if not isinstance(attempt, PlanningAttempt) or (
            attempt.lifecycle is not PlanningAttemptLifecycle.COMPLETED
            or attempt.disposition is not PlanningDisposition.VALID
            or attempt.finalized_plan != plan
        ):
            return Reason.PLAN_INVALID_OR_STALE
        if validation is None:
            return Reason.VALIDATION_UNAVAILABLE
        if not isinstance(policy, PlanPolicyAssessment):
            return Reason.POLICY_NOT_EVALUATED
        if policy.decision is PlanPolicyDecision.DENY:
            return Reason.POLICY_DENIED
        if policy.decision is PlanPolicyDecision.REQUIRES_APPROVAL and (
            context.approval_decision_ref is None
        ):
            return Reason.APPROVAL_REQUIRED
        if policy.decision not in (PlanPolicyDecision.ALLOW, PlanPolicyDecision.REQUIRES_APPROVAL):
            return Reason.POLICY_NOT_EVALUATED
        if attempt.request.source != plan.source or context.manifest_size_bytes is None:
            return Reason.SOURCE_PROVENANCE_MISMATCH
        try:
            checked = _authoritative_request(
                work,
                PlanningAdmissionRequest(
                    mission_ref=request.mission_ref,
                    acquisition_ref=plan.source.acquisition_ref,
                    semantic_inspection_ref=context.semantic_inspection_ref,
                    classification_inspection_ref=context.classification_inspection_ref,
                    planner_profile="m20-d-planning",
                    planner_version="1",
                    policy_profile=attempt.request.policy_profile,
                    policy_version=attempt.request.policy_version,
                ),
            )
        except PlanningAdmissionError:
            return Reason.SOURCE_PROVENANCE_MISMATCH
        if checked.source != plan.source or checked.inspection != attempt.request.inspection:
            return Reason.SOURCE_PROVENANCE_MISMATCH
        if not isinstance(provider, CapabilityProvider) or provider.node_id != request.node_id:
            return Reason.NODE_SELECTION_INVALID
        if (
            provider.availability is not ProviderAvailability.AVAILABLE
            or str(provider.capability_id) != "runtime.prepare"
            or not any(operation.name == "prepare" for operation in provider.definition.operations)
        ):
            return Reason.PROVIDER_SELECTION_INVALID
        if (request.profile_id, request.profile_version) != ("m20-e-python-stdlib-kali", "1"):
            return Reason.PREPARATION_PROFILE_UNSUPPORTED
        if request.budgets is None:
            return Reason.PREPARATION_BUDGET_INVALID
        if set(request.confinement_features) != set(ConfinementFeature) or len(
            request.confinement_features
        ) != len(ConfinementFeature):
            return Reason.CONFINEMENT_REQUIREMENT_INVALID
        from boberagent_contracts.runtime_preparation import PreparationAction

        if set(request.actions) != set(PreparationAction) or len(request.actions) != len(
            PreparationAction
        ):
            return Reason.PREPARATION_ACTION_UNSUPPORTED
        if plan.sensitive_requirements:
            return Reason.SECRET_REQUIREMENT_UNSUPPORTED
        if any(
            dependency.kind
            not in {PlanDependencyKind.STDLIB_MODULE, PlanDependencyKind.LOCAL_MODULE}
            for dependency in plan.dependencies
        ):
            return Reason.DEPENDENCY_REQUIREMENT_UNSUPPORTED
        if (
            plan.runtime.kind != "python"
            or plan.runtime.version_constraint not in {">=3.12,<4", "==3.12.*", "3.12"}
            or plan.runtime.location is not ExecutionLocation.ATTACKER_NODE
            or plan.runtime.platform != "LINUX"
            or plan.runtime.platform_variant != "kali"
            or not plan.runtime.user_space
            or not plan.runtime.noninteractive
            or plan.entrypoint.language != "python"
            or plan.entrypoint.invocation_form != "SCRIPT"
            or plan.resources
            or plan.sessions
        ):
            return Reason.RUNTIME_REQUIREMENT_UNSUPPORTED
        if any(
            rule.destination is not NetworkDestinationClass.SELECTED_TARGET
            for rule in plan.network.rules
        ):
            return Reason.PREPARATION_NETWORK_UNSUPPORTED
        try:
            ConfinementRequirement(required_features=request.confinement_features)
        except ValidationError:
            return Reason.CONFINEMENT_REQUIREMENT_INVALID
        return None

    @staticmethod
    def _spec(
        ref: RuntimePreparationRef, context: PreparationContext, plan: ExecutionPlanV2
    ) -> RuntimePreparationSpec | None:
        if context.request.budgets is None or context.manifest_size_bytes is None:
            return None
        try:
            return RuntimePreparationSpec(
                schema_version="runtime-preparation-spec-v1",
                preparation_ref=ref,
                mission_ref=context.request.mission_ref,
                plan_ref=context.request.plan_ref,
                plan_intent_sha256=context.plan_intent_sha256,
                node_id=context.request.node_id,
                provider_id=context.request.provider_id,
                provider_version=_required(context.provider_version),
                source=PreparationSource(
                    plan_source=context.source, manifest_size_bytes=context.manifest_size_bytes
                ),
                entrypoint=plan.entrypoint,
                runtime=plan.runtime,
                profile=initial_python_preparation_profile(),
                profile_sha256=context.profile_sha256,
                budgets=context.request.budgets,
                allowed_actions=context.request.actions,
            )
        except (ValidationError, ValueError):
            return None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise PreparationAdmissionError("PREPARATION_CLOCK_INVALID")
        return value


def _strict_request(request: PreparationRequest) -> PreparationRequest:
    try:
        if not isinstance(request, PreparationRequest) or (
            set(request.__dict__) - set(PreparationRequest.model_fields)
        ):
            raise ValueError("invalid request")
        return PreparationRequest.model_validate_json(request.model_dump_json())
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise PreparationAdmissionError("PREPARATION_REQUEST_INVALID") from None


def _required[T](value: T | None) -> T:
    if value is None:
        raise PreparationAdmissionError("PREPARATION_AUTHORITY_INCOMPLETE")
    return value


def _policy_decision(value: PlanPolicyDecision | None) -> Literal["ALLOW", "REQUIRES_APPROVAL"]:
    if value is PlanPolicyDecision.ALLOW:
        return "ALLOW"
    if value is PlanPolicyDecision.REQUIRES_APPROVAL:
        return "REQUIRES_APPROVAL"
    raise PreparationAdmissionError("PREPARATION_POLICY_NOT_ELIGIBLE")
