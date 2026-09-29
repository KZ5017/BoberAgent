"""Pure, deterministic D5 checker over typed intent and authoritative snapshots."""

from boberagent_contracts import ExecutionPlanV2, execution_intent_digest
from boberagent_contracts.plan_requirements import (
    EffectScope,
    FilesystemOperation,
    NetworkDestinationClass,
)
from boberagent_contracts.plan_values import NetworkTarget, TargetRole

from .models import PlanValidation, PlanValidationStatus
from .policy_models import NarrowPolicyProfile, PolicyEvaluation, PolicyScopeSnapshot

EVALUATOR_PROFILE = "m20-d5-policy-evaluator"
EVALUATOR_VERSION = "1"
VALIDATOR_PROFILE = "m20-d4-plan-validator"
VALIDATOR_VERSION = "1"


def evaluate_policy(
    plan: ExecutionPlanV2,
    validation: PlanValidation,
    profile: NarrowPolicyProfile,
    scope: PolicyScopeSnapshot,
    *,
    validation_scope_sha256: str,
) -> PolicyEvaluation:
    """Hard mismatches deny; approval is considered only after every check passes.

    Caller has already loaded and revalidated authoritative persisted records.
    This function does not read state, inspect source or contact a target.
    """
    if (
        validation.status is not PlanValidationStatus.VALID
        or (validation.validation_profile, validation.validation_version)
        != (VALIDATOR_PROFILE, VALIDATOR_VERSION)
        or validation.execution_plan_ref != plan.execution_plan_id
        or validation.intent_sha256 != execution_intent_digest(plan)
        or validation.mission_ref != plan.mission_ref
    ):
        raise ValueError("POLICY_VALIDATION_UNAVAILABLE")

    reasons: list[str] = []

    def deny(code: str, condition: bool) -> None:
        if condition:
            reasons.append(code)

    target = plan.target
    deny(
        "POLICY_TARGET_OUT_OF_SCOPE",
        plan.mission_ref != profile.mission_ref
        or scope.mission_ref != plan.mission_ref
        or scope.mission_status != "ACTIVE"
        or not isinstance(target, NetworkTarget)
        or (
            isinstance(target, NetworkTarget)
            and (
                target.role not in profile.allowed_target_roles
                or target.asset_ref not in profile.allowed_asset_refs
                or scope.target_asset_ref != target.asset_ref
                or scope.target_asset_mission_ref != plan.mission_ref
                or scope.target_asset_address != target.address
                or (target.asset_ref, target.address) not in scope.mission_assets
            )
        ),
    )
    if isinstance(target, NetworkTarget):
        deny(
            "POLICY_SERVICE_OUT_OF_SCOPE",
            target.service_ref is not None
            and (
                target.service_ref not in profile.allowed_service_refs
                or scope.target_service_ref != target.service_ref
                or scope.target_service_asset_ref != target.asset_ref
                or scope.target_service_transport != target.transport
                or scope.target_service_port != target.port
            ),
        )
        deny(
            "POLICY_TARGET_ENDPOINT_FORBIDDEN",
            target.role is not TargetRole.SERVICE_ENDPOINT
            or target.port is None
            or target.transport != profile.allowed_network_transport,
        )
    deny("POLICY_SCOPE_CHANGED", validation.scope_sha256 != validation_scope_sha256)

    runtime = plan.runtime
    deny(
        "POLICY_RUNTIME_FORBIDDEN",
        runtime.kind != profile.runtime_kind
        or runtime.location != profile.execution_location
        or runtime.platform != profile.platform
        or runtime.platform_variant != profile.platform_variant
        or runtime.version_constraint != ">=3.12,<4",
    )
    deny("POLICY_PRIVILEGED_FORBIDDEN", not runtime.user_space)
    deny("POLICY_INTERACTIVE_FORBIDDEN", not runtime.noninteractive)
    deny(
        "POLICY_DEPENDENCY_FORBIDDEN",
        any(item.kind not in profile.allowed_dependency_kinds for item in plan.dependencies),
    )

    filesystem = plan.filesystem
    deny(
        "POLICY_UNKNOWN_EFFECT_FORBIDDEN",
        filesystem.scope is EffectScope.UNKNOWN or bool(plan.uncertainties),
    )
    deny(
        "POLICY_FILESYSTEM_EFFECT_FORBIDDEN",
        filesystem.scope is not profile.allowed_filesystem_scope
        or filesystem.writable_root_requirement_id is not None
        or any(
            operation not in profile.allowed_filesystem_operations
            or operation
            in {FilesystemOperation.WRITE, FilesystemOperation.CREATE, FilesystemOperation.DELETE}
            for rule in filesystem.rules
            for operation in rule.operations
        )
        or any(item.scope is not EffectScope.BOUNDED for item in plan.expected_results),
    )

    destinations = tuple(item.destination for item in plan.network.rules)
    deny("POLICY_LISTENER_FORBIDDEN", NetworkDestinationClass.LISTENER_BIND in destinations)
    deny("POLICY_CALLBACK_FORBIDDEN", NetworkDestinationClass.CALLBACK in destinations)
    deny(
        "POLICY_MULTI_TARGET_FORBIDDEN",
        NetworkDestinationClass.MULTI_TARGET in destinations or len(plan.network.rules) > 1,
    )
    deny(
        "POLICY_NETWORK_DESTINATION_FORBIDDEN",
        len(plan.network.rules) != 1
        or any(item is not NetworkDestinationClass.SELECTED_TARGET for item in destinations)
        or (
            isinstance(target, NetworkTarget)
            and (
                target.port is None
                or any(
                    rule.transport != profile.allowed_network_transport
                    or tuple(rule.ports) != (target.port,)
                    for rule in plan.network.rules
                )
            )
        ),
    )
    deny("POLICY_SECRET_USE_FORBIDDEN", bool(plan.sensitive_requirements))
    deny("POLICY_RESOURCE_REQUIREMENT_FORBIDDEN", bool(plan.resources or plan.sessions))

    for field in (
        "wall_time_seconds",
        "process_count",
        "memory_bytes",
        "output_bytes",
        "disk_write_bytes",
    ):
        deny(
            "POLICY_LIMIT_EXCEEDED",
            getattr(plan.limits, field) > getattr(profile.maximum_limits, field),
        )
    if reasons:
        return PolicyEvaluation(decision="DENY", reason_codes=tuple(dict.fromkeys(reasons)))
    if profile.require_operator_approval:
        return PolicyEvaluation(
            decision="REQUIRES_APPROVAL", reason_codes=("POLICY_APPROVAL_REQUIRED",)
        )
    return PolicyEvaluation(decision="ALLOW", reason_codes=("POLICY_ALLOW",))
