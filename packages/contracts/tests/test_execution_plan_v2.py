"""Strict immutable intent, legacy compatibility and canonical identity, not execution."""

import json

import pytest
from boberagent_contracts import (
    AccessMode,
    ArtifactRef,
    CredentialRef,
    ExecutionPlan,
    ExecutionPlanV2,
    ResourceRef,
    SecretRef,
    SessionRef,
    decode_execution_plan,
    execution_intent_digest,
)
from boberagent_contracts.plan_canonical import canonical_json, canonical_value
from boberagent_contracts.plan_requirements import (
    CredentialRequirement,
    EffectScope,
    ResourceRequirement,
    SecretRequirement,
    SessionRequirement,
)
from boberagent_contracts.plan_values import (
    BindingProvenance,
    CredentialValue,
    DeliveryChannel,
    LiteralValue,
    NetworkTarget,
    ParameterBinding,
    ResolutionState,
    SecretValue,
    SourceTarget,
    TargetRole,
    ValueType,
)
from plan_test_fixtures import plan_fixture
from pydantic import TypeAdapter, ValidationError


def test_v2_serialization_and_strict_schema() -> None:
    plan = plan_fixture()
    restored = decode_execution_plan(plan.model_dump_json())
    assert isinstance(restored, ExecutionPlanV2)
    assert restored == plan
    assert restored.model_json_schema()["additionalProperties"] is False
    assert restored.schema_version == "execution-plan-v2"
    assert "status" not in type(restored).model_fields
    data = plan.model_dump(mode="json")
    for name in ("metadata", "execution_authorization", "transport_grant", "status"):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ExecutionPlanV2.model_validate({**data, name: "APPROVED"})


def test_unversioned_legacy_decode_remains_legacy_not_executor_eligible() -> None:
    payload = {
        "execution_plan_id": "legacy-plan",
        "source_artifact_ref": "artifact-1",
        "status": "APPROVED",
        "runtime_type": "python",
        "entrypoint": "check.py",
        "isolation": {"profile": "venv"},
        "created_at": "2026-09-29T12:00:00Z",
    }
    legacy = decode_execution_plan(json.dumps(payload))
    assert isinstance(legacy, ExecutionPlan)
    assert not isinstance(legacy, ExecutionPlanV2)
    assert legacy.schema_version == "execution-plan-v1"
    assert decode_execution_plan(legacy.model_dump_json()) == legacy
    with pytest.raises(ValidationError):
        decode_execution_plan(json.dumps({**payload, "schema_version": "execution-plan-v99"}))


def test_deep_immutability_and_detached_input_collections() -> None:
    plan = plan_fixture()
    original = plan.model_dump_json()
    for item, field in (
        (plan, "target"),
        (plan.target, "address"),
        (plan.invocation, "arguments"),
        (plan.bindings[0], "value"),
        (plan.bindings[0].provenance, "evidence_ids"),
        (plan.network.rules[0], "ports"),
        (plan.source, "raw_sha256"),
    ):
        with pytest.raises(ValidationError, match="frozen_instance"):
            setattr(item, field, None)
    assert isinstance(plan.invocation.arguments, tuple)
    assert isinstance(plan.network.rules[0].ports, tuple)
    data = plan.model_dump(mode="json")
    restored = ExecutionPlanV2.model_validate(data)
    data["bindings"].clear()
    assert restored == plan
    assert plan.model_dump_json() == original


def test_canonical_sets_maps_but_ordered_arguments_change_digest() -> None:
    plan = plan_fixture()
    data = plan.model_dump(mode="json")
    data["bindings"].reverse()
    data["network"]["rules"][0]["ports"] = [80, 443]
    first = ExecutionPlanV2.model_validate(data)
    data["bindings"].reverse()
    data["network"]["rules"][0]["ports"].reverse()
    second = ExecutionPlanV2.model_validate(data)
    assert execution_intent_digest(first) == execution_intent_digest(second)
    data["invocation"]["arguments"].reverse()
    ordered = ExecutionPlanV2.model_validate(data)
    assert ordered.invocation.arguments == tuple(reversed(first.invocation.arguments))
    assert execution_intent_digest(ordered) != execution_intent_digest(first)
    data = plan.model_dump(mode="json")
    data.update(execution_plan_id="another-plan", created_at="2026-09-30T12:00:00Z")
    assert execution_intent_digest(ExecutionPlanV2.model_validate(data)) == execution_intent_digest(
        plan
    )
    assert canonical_json(canonical_value({"b": 2, "a": 1})) == canonical_json(
        canonical_value({"a": 1, "b": 2})
    )


def test_secret_and_credential_requirements_are_refs_only() -> None:
    plan = plan_fixture()
    bindings = (
        ParameterBinding(
            binding_id="password",
            parameter_id="password",
            value_type=ValueType.SECRET,
            channel=DeliveryChannel.STANDARD_INPUT,
            required=True,
            resolution=ResolutionState.RESOLVED,
            value=SecretValue(secret_ref=SecretRef("secret-safe")),
            provenance=BindingProvenance(origin="OPERATOR", answer_id="answer-1"),
        ),
        ParameterBinding(
            binding_id="account",
            parameter_id="account",
            value_type=ValueType.CREDENTIAL,
            channel=DeliveryChannel.STANDARD_INPUT,
            required=True,
            resolution=ResolutionState.RESOLVED,
            value=CredentialValue(
                credential_ref=CredentialRef("credential-safe"), secret_role="token"
            ),
            provenance=BindingProvenance(origin="OPERATOR", answer_id="answer-2"),
        ),
    )
    data = plan.model_dump()
    data["bindings"] = (*plan.bindings, *bindings)
    data["sensitive_requirements"] = (
        SecretRequirement(
            secret_ref=SecretRef("secret-safe"),
            binding_id="password",
            role="password",
            purpose="bounded authentication",
        ),
        CredentialRequirement(
            credential_ref=CredentialRef("credential-safe"),
            binding_id="account",
            role="token",
            purpose="bounded authentication",
        ),
    )
    sensitive = ExecutionPlanV2.model_validate(data)
    serialized = sensitive.model_dump_json()
    assert "secret-safe" in serialized and "credential-safe" in serialized
    assert "plaintext" not in serialized and "transport_grant" not in serialized
    assert decode_execution_plan(serialized) == sensitive
    with pytest.raises(ValidationError, match="cannot substitute"):
        ParameterBinding(
            binding_id="password",
            parameter_id="password",
            value_type=ValueType.SECRET,
            channel=DeliveryChannel.ARGUMENT,
            required=True,
            resolution=ResolutionState.RESOLVED,
            value=LiteralValue(value="not-a-ref"),
            provenance=BindingProvenance(origin="OPERATOR"),
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SecretValue.model_validate({"secret_ref": "secret-safe", "plaintext": "test-value"})


@pytest.mark.parametrize("role", [TargetRole.FILE, TargetRole.DIRECTORY, TargetRole.REPOSITORY])
def test_source_targets_are_not_network_targets(role: TargetRole) -> None:
    source = SourceTarget.model_validate(
        {
            "role": role.value,
            "artifact_ref": "artifact-input",
            "relative_path": "input/data",
        }
    )
    assert source.artifact_ref == ArtifactRef("artifact-input")
    with pytest.raises(ValidationError):
        NetworkTarget.model_validate(source.model_dump())
    assert TypeAdapter(TargetRole).validate_python(role.value) is role


@pytest.mark.parametrize(
    "path", ["../escape.py", "/absolute.py", "a/../b", "a//b", "C:\\x", "a\x00b"]
)
def test_entrypoint_path_confined_lexically(path: str) -> None:
    data = plan_fixture().model_dump(mode="json")
    data["entrypoint"]["relative_path"] = path
    with pytest.raises(ValidationError):
        ExecutionPlanV2.model_validate(data)


def test_target_mismatch_unresolved_bindings_and_unbounded_limits_rejected() -> None:
    data = plan_fixture().model_dump(mode="json")
    data["bindings"][0]["value"]["target_role"] = "DIRECTORY"
    with pytest.raises(ValidationError, match="role mismatch"):
        ExecutionPlanV2.model_validate(data)
    data = plan_fixture().model_dump(mode="json")
    data["bindings"][0].update(resolution="UNRESOLVED", value=None)
    with pytest.raises(ValidationError, match="partial proposals"):
        ExecutionPlanV2.model_validate(data)
    data = plan_fixture().model_dump(mode="json")
    data["runtime"]["user_space"] = "true"
    with pytest.raises(ValidationError):
        ExecutionPlanV2.model_validate(data)
    for invalid in (0, -1, "unlimited", float("inf"), True):
        data = plan_fixture().model_dump(mode="json")
        data["limits"]["wall_time_seconds"] = invalid
        with pytest.raises(ValidationError):
            ExecutionPlanV2.model_validate(data)


def test_resource_session_requirement_is_distinct_from_allocated_reference() -> None:
    requirement = ResourceRequirement(
        requirement_id="callback",
        resource_type="listener",
        purpose="bounded callback",
        access_mode=AccessMode.EXCLUSIVE,
    )
    assert requirement.existing_ref is None
    registered = ResourceRequirement.model_validate(
        {**requirement.model_dump(), "existing_ref": ResourceRef("resource-1")}
    )
    assert registered.existing_ref == ResourceRef("resource-1")
    session = SessionRequirement(
        requirement_id="incoming",
        session_type="command",
        purpose="callback",
        access_mode=AccessMode.SHARED,
        resource_requirement_id="callback",
        existing_ref=SessionRef("session-1"),
    )
    assert session.existing_ref == SessionRef("session-1")
    with pytest.raises(ValidationError):
        ResourceRequirement.model_validate(
            {**requirement.model_dump(), "existing_ref": SessionRef("session-wrong")}
        )
    data = plan_fixture().model_dump(mode="json")
    data["filesystem"]["scope"] = "UNKNOWN"
    unknown = ExecutionPlanV2.model_validate(data)
    assert unknown.filesystem.scope is EffectScope.UNKNOWN


def test_environment_dependencies_and_typed_value_sources() -> None:
    from boberagent_contracts.plan_requirements import PlanDependency, PlanDependencyKind
    from boberagent_contracts.plan_values import (
        CallbackValue,
        EnvironmentBinding,
        ManagedPathValue,
        OperatorValue,
        SourcePathValue,
    )

    plan = plan_fixture()
    binding = ParameterBinding(
        binding_id="mode",
        parameter_id="mode",
        value_type=ValueType.TEXT,
        channel=DeliveryChannel.ENVIRONMENT,
        required=True,
        resolution=ResolutionState.RESOLVED,
        value=OperatorValue(answer_id="answer-mode", value="check"),
        provenance=BindingProvenance(origin="OPERATOR", answer_id="answer-mode"),
    )
    data = plan.model_dump()
    data["bindings"] = (*plan.bindings, binding)
    data["environment"] = (EnvironmentBinding(name="CHECK_MODE", binding_id="mode"),)
    data["dependencies"] = tuple(
        PlanDependency(
            dependency_id=f"dependency-{kind.value}",
            kind=kind,
            identifier="module",
            evidence_ids=("dependency-evidence",),
        )
        for kind in PlanDependencyKind
    )
    extended = ExecutionPlanV2.model_validate(data)
    assert decode_execution_plan(extended.model_dump_json()) == extended
    with pytest.raises(ValidationError, match="source and value type"):
        ParameterBinding(
            binding_id="callback",
            parameter_id="port",
            value_type=ValueType.SECRET,
            channel=DeliveryChannel.ARGUMENT,
            required=True,
            resolution=ResolutionState.RESOLVED,
            value=CallbackValue(requirement_id="listener", component="port"),
            provenance=BindingProvenance(origin="PLANNING"),
        )
    data["environment"] = [dict(name="CHECK_MODE", binding_id="target")]
    with pytest.raises(ValidationError, match="environment-channel"):
        ExecutionPlanV2.model_validate(data)
    for value in (
        CallbackValue(requirement_id="listener", component="port"),
        ManagedPathValue(requirement_id="workspace", relative_path="output/data.txt"),
        SourcePathValue(artifact_ref=ArtifactRef("artifact-input"), relative_path="input/data.txt"),
    ):
        assert type(value).model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        ManagedPathValue.model_validate(
            {"requirement_id": "workspace", "relative_path": "/tmp/live"}
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ExecutionPlanV2.model_validate({**plan.model_dump(), "inherit_environment": True})


@pytest.mark.parametrize(
    ("role", "address", "extra"),
    [
        ("HOST", "lab.example", {}),
        ("IP", "2001:db8::1", {}),
        ("URL", "https://lab.example/check", {}),
        (
            "SERVICE_ENDPOINT",
            "127.0.0.1",
            {"port": 80, "transport": "tcp", "service_ref": "service-1"},
        ),
    ],
)
def test_distinct_explicit_network_target_roles(
    role: str, address: str, extra: dict[str, object]
) -> None:
    target = NetworkTarget.model_validate(
        {"role": role, "asset_ref": "asset-1", "address": address, **extra}
    )
    assert target.role.value == role and target.address == address
    assert NetworkTarget.model_validate_json(target.model_dump_json()) == target
    with pytest.raises(ValidationError):
        NetworkTarget.model_validate(
            {"role": "IP", "asset_ref": "asset-1", "address": "input/file.txt"}
        )


def test_network_filesystem_constraints_and_expected_evidence_are_not_authority() -> None:
    from boberagent_contracts.plan_requirements import (
        ExpectedResult,
        FilesystemConstraints,
        FilesystemOperation,
        FilesystemRule,
        NetworkConstraints,
    )

    plan = plan_fixture()
    rule = FilesystemRule(
        root_requirement_id="workspace",
        relative_path="output/*.json",
        match="PATTERN",
        operations=(FilesystemOperation.WRITE,),
    )
    filesystem = FilesystemConstraints(
        writable_root_requirement_id="workspace",
        scope=EffectScope.UNKNOWN,
        rules=(rule,),
        cleanup="REMOVE_MANAGED_WRITES",
    )
    assert filesystem.scope is EffectScope.UNKNOWN
    with pytest.raises(ValidationError, match="managed writable root"):
        FilesystemConstraints.model_validate(
            {**filesystem.model_dump(), "writable_root_requirement_id": None}
        )
    with pytest.raises(ValidationError):
        NetworkConstraints.model_validate({"unspecified": "ALLOW"})
    data = plan.model_dump()
    data["expected_results"] = (
        ExpectedResult(
            semantic_type="target.not_confirmed",
            evidence_ids=("stdout",),
            scope=EffectScope.BOUNDED,
        ),
    )
    expected = ExecutionPlanV2.model_validate(data)
    assert "target.not_confirmed" in expected.model_dump_json()
    assert "authorization" not in expected.model_dump_json()
    data["expected_results"] = (
        ExpectedResult(
            semantic_type="target.not_confirmed",
            evidence_ids=("undeclared",),
            scope=EffectScope.BOUNDED,
        ),
    )
    with pytest.raises(ValidationError, match="declared evidence"):
        ExecutionPlanV2.model_validate(data)
