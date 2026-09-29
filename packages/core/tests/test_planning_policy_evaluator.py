"""D5 pure checker hard-deny matrix; no source or runtime work."""

from pathlib import Path

import pytest
from boberagent_contracts import (
    CredentialRef,
    ExecutionPlanV2,
    SecretRef,
    ServiceRef,
    execution_intent_digest,
)
from boberagent_contracts.enums import AccessMode
from boberagent_contracts.plan_requirements import (
    CredentialRequirement,
    EffectScope,
    ExecutionLocation,
    FilesystemConstraints,
    FilesystemOperation,
    FilesystemRule,
    NetworkConstraints,
    NetworkDestinationClass,
    NetworkRule,
    PlanDependency,
    PlanDependencyKind,
    ResourceRequirement,
    SecretRequirement,
    SessionRequirement,
)
from boberagent_contracts.plan_values import (
    BindingProvenance,
    CredentialValue,
    DeliveryChannel,
    EnvironmentBinding,
    NetworkTarget,
    ParameterBinding,
    ResolutionState,
    SecretValue,
    ValueType,
)
from boberagent_core import CoreDatabase
from boberagent_core.planning.models import PlanValidationStatus
from boberagent_core.planning.policy_evaluator import evaluate_policy
from boberagent_core.planning.policy_models import PolicyScopeSnapshot
from test_planning_policy import _plan, _profile


def _scope(plan: ExecutionPlanV2) -> PolicyScopeSnapshot:
    assert isinstance(plan.target, NetworkTarget)
    return PolicyScopeSnapshot(
        mission_ref=plan.mission_ref,
        mission_status="ACTIVE",
        mission_assets=((plan.target.asset_ref, plan.target.address),),
        target_asset_ref=plan.target.asset_ref,
        target_asset_mission_ref=plan.mission_ref,
        target_asset_address=plan.target.address,
        target_service_ref=None,
        target_service_asset_ref=None,
        target_service_transport=None,
        target_service_port=None,
        target_service_state=None,
    )


def _modified(plan: ExecutionPlanV2, **changes: object) -> ExecutionPlanV2:
    """Negative fixtures still pass the strict shared v2 schema."""
    return ExecutionPlanV2.model_validate(plan.model_dump() | changes)


def _secret_plan(plan: ExecutionPlanV2, *, credential: bool) -> ExecutionPlanV2:
    value = (
        CredentialValue(credential_ref=CredentialRef("credential-fixture"), secret_role="password")
        if credential
        else SecretValue(secret_ref=SecretRef("secret-fixture"))
    )
    binding = ParameterBinding(
        binding_id="sensitive",
        parameter_id="parameter-sensitive",
        value_type=ValueType.CREDENTIAL if credential else ValueType.SECRET,
        channel=DeliveryChannel.ENVIRONMENT,
        required=True,
        resolution=ResolutionState.RESOLVED,
        value=value,
        provenance=BindingProvenance(origin="PLANNING"),
    )
    requirement = (
        CredentialRequirement(
            credential_ref=CredentialRef("credential-fixture"),
            role="password",
            purpose="test",
            binding_id="sensitive",
        )
        if credential
        else SecretRequirement(
            secret_ref=SecretRef("secret-fixture"),
            role="password",
            purpose="test",
            binding_id="sensitive",
        )
    )
    return _modified(
        plan,
        bindings=(*plan.bindings, binding),
        environment=(EnvironmentBinding(name="POC_SECRET", binding_id="sensitive"),),
        sensitive_requirements=(requirement,),
    )


def _other_rule(destination: NetworkDestinationClass) -> NetworkRule:
    return NetworkRule(
        destination=destination, requirement_id="other-endpoint", transport="tcp", ports=(443,)
    )


def test_pure_checker_rejects_every_narrow_hard_boundary(
    database: CoreDatabase, tmp_path: Path
) -> None:
    plan, validation = _plan(database, tmp_path)
    assert isinstance(plan.target, NetworkTarget)
    scope = _scope(plan)
    profile = _profile(plan)
    cases: tuple[tuple[str, ExecutionPlanV2, PolicyScopeSnapshot], ...] = (
        (
            "POLICY_RUNTIME_FORBIDDEN",
            _modified(plan, runtime=plan.runtime.model_copy(update={"kind": "shell"})),
            scope,
        ),
        (
            "POLICY_RUNTIME_FORBIDDEN",
            _modified(
                plan, runtime=plan.runtime.model_copy(update={"location": ExecutionLocation.TARGET})
            ),
            scope,
        ),
        (
            "POLICY_INTERACTIVE_FORBIDDEN",
            _modified(plan, runtime=plan.runtime.model_copy(update={"noninteractive": False})),
            scope,
        ),
        (
            "POLICY_PRIVILEGED_FORBIDDEN",
            _modified(plan, runtime=plan.runtime.model_copy(update={"user_space": False})),
            scope,
        ),
        (
            "POLICY_DEPENDENCY_FORBIDDEN",
            _modified(
                plan,
                dependencies=(
                    PlanDependency(
                        dependency_id="third",
                        kind=PlanDependencyKind.THIRD_PARTY_PACKAGE,
                        identifier="requests",
                    ),
                ),
            ),
            scope,
        ),
        (
            "POLICY_UNKNOWN_EFFECT_FORBIDDEN",
            _modified(
                plan,
                filesystem=FilesystemConstraints(
                    scope=EffectScope.UNKNOWN, cleanup="RETAIN_EVIDENCE"
                ),
            ),
            scope,
        ),
        (
            "POLICY_FILESYSTEM_EFFECT_FORBIDDEN",
            _modified(
                plan,
                filesystem=FilesystemConstraints(
                    scope=EffectScope.BROAD, cleanup="RETAIN_EVIDENCE"
                ),
            ),
            scope,
        ),
        (
            "POLICY_FILESYSTEM_EFFECT_FORBIDDEN",
            _modified(
                plan,
                filesystem=FilesystemConstraints(
                    scope=EffectScope.BOUNDED,
                    writable_root_requirement_id="writes",
                    rules=(
                        FilesystemRule(
                            root_requirement_id="writes",
                            relative_path="out.txt",
                            operations=(FilesystemOperation.WRITE,),
                        ),
                    ),
                    cleanup="RETAIN_EVIDENCE",
                ),
            ),
            scope,
        ),
        (
            "POLICY_NETWORK_DESTINATION_FORBIDDEN",
            _modified(
                plan,
                network=NetworkConstraints(
                    rules=(_other_rule(NetworkDestinationClass.PUBLIC_INTERNET),)
                ),
            ),
            scope,
        ),
        (
            "POLICY_CALLBACK_FORBIDDEN",
            _modified(
                plan,
                network=NetworkConstraints(rules=(_other_rule(NetworkDestinationClass.CALLBACK),)),
            ),
            scope,
        ),
        (
            "POLICY_LISTENER_FORBIDDEN",
            _modified(
                plan,
                network=NetworkConstraints(
                    rules=(_other_rule(NetworkDestinationClass.LISTENER_BIND),)
                ),
            ),
            scope,
        ),
        (
            "POLICY_MULTI_TARGET_FORBIDDEN",
            _modified(
                plan,
                network=NetworkConstraints(
                    rules=(*plan.network.rules, _other_rule(NetworkDestinationClass.MULTI_TARGET))
                ),
            ),
            scope,
        ),
        ("POLICY_SECRET_USE_FORBIDDEN", _secret_plan(plan, credential=False), scope),
        ("POLICY_SECRET_USE_FORBIDDEN", _secret_plan(plan, credential=True), scope),
        (
            "POLICY_RESOURCE_REQUIREMENT_FORBIDDEN",
            _modified(
                plan,
                resources=(
                    ResourceRequirement(
                        requirement_id="browser",
                        resource_type="browser",
                        purpose="test",
                        access_mode=AccessMode.SHARED,
                    ),
                ),
            ),
            scope,
        ),
        (
            "POLICY_RESOURCE_REQUIREMENT_FORBIDDEN",
            _modified(
                plan,
                sessions=(
                    SessionRequirement(
                        requirement_id="session",
                        session_type="shell",
                        purpose="test",
                        access_mode=AccessMode.SHARED,
                    ),
                ),
            ),
            scope,
        ),
        (
            "POLICY_SERVICE_OUT_OF_SCOPE",
            _modified(
                plan,
                target=plan.target.model_copy(update={"service_ref": ServiceRef("service-other")}),
            ),
            scope,
        ),
        (
            "POLICY_UNKNOWN_EFFECT_FORBIDDEN",
            _modified(plan, uncertainties=("material-unknown",)),
            scope,
        ),
        (
            "POLICY_NETWORK_DESTINATION_FORBIDDEN",
            _modified(plan, network=NetworkConstraints()),
            scope,
        ),
    )
    for expected, candidate, current_scope in cases:
        matching_validation = validation.model_copy(
            update={"intent_sha256": execution_intent_digest(candidate)}
        )
        result = evaluate_policy(
            candidate,
            matching_validation,
            profile,
            current_scope,
            validation_scope_sha256=validation.scope_sha256,
        )
        assert result.decision == "DENY" and expected in result.reason_codes, expected
        assert "POLICY_APPROVAL_REQUIRED" not in result.reason_codes

    for field in (
        "wall_time_seconds",
        "process_count",
        "memory_bytes",
        "output_bytes",
        "disk_write_bytes",
    ):
        limits = plan.limits.model_copy(update={field: getattr(plan.limits, field) + 1})
        candidate = _modified(plan, limits=limits)
        matching = validation.model_copy(
            update={"intent_sha256": execution_intent_digest(candidate)}
        )
        assessment = evaluate_policy(
            candidate,
            matching,
            profile,
            scope,
            validation_scope_sha256=validation.scope_sha256,
        )
        assert assessment.decision == "DENY"
        assert "POLICY_LIMIT_EXCEEDED" in assessment.reason_codes


@pytest.mark.parametrize("change", ["invalid", "digest", "profile"])
def test_validation_prerequisite_cannot_be_bypassed(
    database: CoreDatabase, tmp_path: Path, change: str
) -> None:
    plan, validation = _plan(database, tmp_path)
    if change == "invalid":
        validation = validation.model_copy(update={"status": PlanValidationStatus.INVALID})
    elif change == "digest":
        validation = validation.model_copy(update={"intent_sha256": "0" * 64})
    else:
        validation = validation.model_copy(update={"validation_version": "0"})
    with pytest.raises(ValueError, match="POLICY_VALIDATION_UNAVAILABLE"):
        evaluate_policy(
            plan,
            validation,
            _profile(plan),
            _scope(plan),
            validation_scope_sha256=validation.scope_sha256,
        )
