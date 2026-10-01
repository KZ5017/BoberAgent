"""Authoritative D5 policy assessment pump; no approval or execution path."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from boberagent_contracts import ExecutionPlanRef, MissionRef
from boberagent_contracts._base import FrozenContractModel
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_values import NetworkTarget

from boberagent_core.clock import utc_now
from boberagent_core.persistence import CoreDatabase
from boberagent_core.persistence.repositories import CoreUnitOfWork

from .construction_models import PlanningScope, PlanningScopeAsset
from .errors import PlanningConflict
from .fingerprints import decision_context_fingerprint
from .models import (
    DecisionContext,
    InitialPlanPolicyProfile,
    PlanningAttemptLifecycle,
    PlanningDisposition,
    PlanPolicyAssessment,
    PlanPolicyDecision,
    PlanValidationStatus,
)
from .policy_evaluator import EVALUATOR_PROFILE, EVALUATOR_VERSION, evaluate_policy
from .policy_models import (
    NarrowPolicyProfile,
    PolicyAssessmentResult,
    PolicyScopeSnapshot,
)
from .records import PlanDecisionRecord, PlanDecisionRef, PolicyDocument, ValidationDocument


class PolicyAssessmentError(ValueError):
    """Bounded errors; never render policy contents or untrusted source text."""


class PolicyProfileRegistry:
    """Trusted Core composition supplies immutable, Mission-scoped policy documents.

    An evaluation caller may select only the profile already pinned by D3. No
    arbitrary per-call JSON, permissive fallback or mutable global defaults exist.
    """

    def __init__(self, profiles: tuple[NarrowPolicyProfile, ...]) -> None:
        by_key: dict[tuple[MissionRef, str, str], NarrowPolicyProfile] = {}
        for submitted in profiles:
            profile = NarrowPolicyProfile.model_validate_json(submitted.model_dump_json())
            key = (profile.mission_ref, profile.profile, profile.version)
            if key in by_key:
                raise ValueError("POLICY_PROFILE_IDENTITY_CONFLICT")
            by_key[key] = profile
        self._profiles = by_key

    def get(self, mission_ref: MissionRef, profile: str, version: str) -> NarrowPolicyProfile:
        found = self._profiles.get((mission_ref, profile, version))
        if found is None:
            raise PolicyAssessmentError("POLICY_PROFILE_UNAVAILABLE")
        return found


class _PolicyContextState(FrozenContractModel):
    """Canonical reference/status-only input to D2's prerequisite digest."""

    validation_decision_ref: PlanDecisionRef
    validation_sha256: str
    policy_sha256: str
    scope: PolicyScopeSnapshot
    evaluator_profile: str
    evaluator_version: str


class CorePlanPolicyService:
    """Explicit assessment pump; ALLOW never means readiness or permission."""

    def __init__(
        self,
        database: CoreDatabase,
        registry: PolicyProfileRegistry,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._registry = registry
        self._clock = clock

    def get_assessment(self, decision_ref: PlanDecisionRef) -> PolicyAssessmentResult | None:
        """Historical lookup only, not a current applicability determination."""
        with self._database.unit_of_work() as work:
            record = work.plan_decisions.get(decision_ref)
            if record is None or not isinstance(record.document, PolicyDocument):
                return None
            digest = record.document.value.policy_sha256
            if digest is None:
                raise PolicyAssessmentError("POLICY_DIGEST_MISSING")
            return PolicyAssessmentResult(record=record, policy_sha256=digest)

    def evaluate(self, plan_ref: ExecutionPlanRef) -> PolicyAssessmentResult:
        result = self._assess(plan_ref, persist=True)
        assert result is not None
        return result

    def current_assessment(self, plan_ref: ExecutionPlanRef) -> PolicyAssessmentResult | None:
        """Return only an already-recorded D5 assessment for today's trusted context.

        This is deliberately read-only: a preparation admission cannot silently run D5.
        Missing trusted policy configuration or changed context fails closed.
        """
        return self._assess(plan_ref, persist=False)

    def _assess(
        self, plan_ref: ExecutionPlanRef, *, persist: bool
    ) -> PolicyAssessmentResult | None:
        try:
            with self._database.unit_of_work() as work:
                stored = work.execution_plans.get(plan_ref)
                if stored is None:
                    raise PolicyAssessmentError("PLAN_NOT_FOUND")
                plan = stored.plan
                attempt = work.planning_attempts.get(stored.planning_attempt_ref)
                if (
                    attempt is None
                    or attempt.lifecycle is not PlanningAttemptLifecycle.COMPLETED
                    or attempt.disposition is not PlanningDisposition.VALID
                    or attempt.finalized_plan != plan
                ):
                    raise PolicyAssessmentError("PLAN_NOT_VALIDATED")
                validation_records = tuple(
                    item
                    for item in work.plan_decisions.list_for_plan(plan_ref)
                    if isinstance(item.document, ValidationDocument)
                    and item.document.value.validation_profile == "m20-d4-plan-validator"
                    and item.document.value.validation_version == "1"
                    and item.document.value.status is PlanValidationStatus.VALID
                    and item.document.value.intent_sha256 == stored.intent_sha256
                    and item.document.value.execution_plan_ref == plan_ref
                )
                if len(validation_records) != 1:
                    raise PolicyAssessmentError("VALIDATION_UNAVAILABLE")
                validation_record = validation_records[0]
                if not isinstance(validation_record.document, ValidationDocument):
                    raise PolicyAssessmentError("VALIDATION_UNAVAILABLE")
                validation = validation_record.document.value
                profile = self._registry.get(
                    plan.mission_ref,
                    attempt.request.policy_profile,
                    attempt.request.policy_version,
                )
                scope = _current_scope(work, plan)
                validation_scope = canonical_digest(
                    PlanningScope(
                        mission_ref=plan.mission_ref,
                        assets=tuple(
                            PlanningScopeAsset(asset_ref=ref, address=address)
                            for ref, address in scope.mission_assets
                        ),
                    )
                )
                assessment = evaluate_policy(
                    plan,
                    validation,
                    profile,
                    scope,
                    validation_scope_sha256=validation_scope,
                )
                context = DecisionContext(
                    mission_ref=plan.mission_ref,
                    intent_sha256=stored.intent_sha256,
                    scope_sha256=validation_scope,
                    classification_sha256=attempt.request.inspection.classification_sha256,
                    validation_profile=validation.validation_profile,
                    validation_version=validation.validation_version,
                    policy=InitialPlanPolicyProfile(maximum_limits=profile.maximum_limits),
                    prerequisite_state_sha256=canonical_digest(
                        _PolicyContextState(
                            validation_decision_ref=validation_record.decision_ref,
                            validation_sha256=canonical_digest(validation),
                            policy_sha256=profile.digest,
                            scope=scope,
                            evaluator_profile=EVALUATOR_PROFILE,
                            evaluator_version=EVALUATOR_VERSION,
                        )
                    ),
                )
                fingerprint = decision_context_fingerprint(context)
                previous = tuple(
                    item
                    for item in work.plan_decisions.find_by_context(plan_ref, fingerprint)
                    if isinstance(item.document, PolicyDocument)
                )
                if previous:
                    existing = previous[0]
                    if (
                        len(previous) != 1
                        or not isinstance(existing.document, PolicyDocument)
                        or existing.document.value.policy_sha256 != profile.digest
                        or existing.document.value.decision
                        != PlanPolicyDecision(assessment.decision)
                        or existing.document.value.reason_codes != assessment.reason_codes
                    ):
                        raise PlanningConflict("policy context identifies conflicting history")
                    return PolicyAssessmentResult(record=existing, policy_sha256=profile.digest)
                if not persist:
                    return None
                now = self._clock()
                if now.tzinfo is None or now.utcoffset() != timedelta(0):
                    raise PolicyAssessmentError("POLICY_CLOCK_INVALID")
                record = PlanDecisionRecord(
                    decision_ref=PlanDecisionRef(f"plan-decision-{uuid4().hex}"),
                    document=PolicyDocument(
                        value=PlanPolicyAssessment(
                            execution_plan_ref=plan_ref,
                            intent_sha256=stored.intent_sha256,
                            mission_ref=plan.mission_ref,
                            scope_sha256=validation_scope,
                            policy_profile=profile.profile,
                            policy_version=profile.version,
                            policy_sha256=profile.digest,
                            decision=PlanPolicyDecision(assessment.decision),
                            evaluator_profile=EVALUATOR_PROFILE,
                            evaluator_version=EVALUATOR_VERSION,
                            reason_codes=assessment.reason_codes,
                            assessed_at=now,
                        )
                    ),
                    context=context,
                    created_at=now,
                )
                persisted = work.plan_decisions.append(record)
                return PolicyAssessmentResult(record=persisted, policy_sha256=profile.digest)
        except (PolicyAssessmentError, PlanningConflict):
            raise
        except Exception:
            raise PolicyAssessmentError("POLICY_EVALUATION_UNAVAILABLE") from None


def _current_scope(work: CoreUnitOfWork, plan: object) -> PolicyScopeSnapshot:
    from boberagent_contracts import ExecutionPlanV2

    if not isinstance(plan, ExecutionPlanV2):
        raise PolicyAssessmentError("PLAN_SCHEMA_UNSUPPORTED")
    mission = work.missions.get(plan.mission_ref)
    if mission is None:
        raise PolicyAssessmentError("MISSION_NOT_FOUND")
    target = plan.target
    asset = work.assets.get(target.asset_ref) if isinstance(target, NetworkTarget) else None
    service = (
        work.services.get(target.service_ref)
        if isinstance(target, NetworkTarget) and target.service_ref is not None
        else None
    )
    return PolicyScopeSnapshot(
        mission_ref=mission.mission_ref,
        mission_status=mission.status,
        mission_assets=tuple(
            (item.asset_ref, item.primary_address)
            for item in work.assets.list_for_mission(mission.mission_ref)
        ),
        target_asset_ref=asset.asset_ref if asset else None,
        target_asset_mission_ref=asset.mission_ref if asset else None,
        target_asset_address=asset.primary_address if asset else None,
        target_service_ref=service.service_ref if service else None,
        target_service_asset_ref=service.asset_ref if service else None,
        target_service_transport=service.transport if service else None,
        target_service_port=service.port if service else None,
        target_service_state=service.state if service else None,
    )
