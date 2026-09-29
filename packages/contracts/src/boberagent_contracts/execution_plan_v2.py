"""ExecutionPlan schema v2: immutable intent, never permission to execute."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from ._base import FrozenContractModel, SymbolicName
from .execution_plan import ExecutionPlan
from .plan_canonical import canonical_digest
from .plan_requirements import (
    CredentialRequirement,
    ExecutionLimits,
    ExpectedEvidence,
    ExpectedResult,
    FilesystemConstraints,
    NetworkConstraints,
    PlanDependency,
    PlanSource,
    ResourceRequirement,
    RuntimeRequirement,
    SecretRequirement,
    SessionRequirement,
)
from .plan_values import (
    BindingToken,
    CredentialValue,
    DeliveryChannel,
    EntrypointIntent,
    EnvironmentBinding,
    InvocationLayout,
    MissionTargetValue,
    OptionValueToken,
    ParameterBinding,
    PlanTarget,
    PositionalToken,
    ResolutionState,
    SecretValue,
    UnknownTarget,
)
from .refs import ExecutionPlanRef, MissionRef

type SensitiveRequirement = Annotated[
    SecretRequirement | CredentialRequirement, Field(discriminator="kind")
]


class ExecutionPlanV2(FrozenContractModel):
    """Finalized intent. Schema consistency checks do not assess policy or source truth."""

    schema_version: Literal["execution-plan-v2"] = "execution-plan-v2"
    intent_profile: Literal["m20-d-intent"] = "m20-d-intent"
    intent_profile_version: Literal["1"] = "1"
    execution_plan_id: ExecutionPlanRef
    mission_ref: MissionRef
    source: PlanSource
    target: PlanTarget
    entrypoint: EntrypointIntent
    runtime: RuntimeRequirement
    invocation: InvocationLayout
    bindings: tuple[ParameterBinding, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    environment: tuple[EnvironmentBinding, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    dependencies: tuple[PlanDependency, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    sensitive_requirements: tuple[SensitiveRequirement, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    resources: tuple[ResourceRequirement, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    sessions: tuple[SessionRequirement, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    filesystem: FilesystemConstraints
    network: NetworkConstraints
    limits: ExecutionLimits
    expected_evidence: tuple[ExpectedEvidence, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )
    expected_results: tuple[ExpectedResult, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    uncertainties: tuple[SymbolicName, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    created_at: AwareDatetime

    @model_validator(mode="after")
    def shape(self) -> Self:
        if isinstance(self.target, UnknownTarget):
            raise ValueError("finalized intent requires a resolved target role")
        bindings = {binding.binding_id: binding for binding in self.bindings}
        if len(bindings) != len(self.bindings):
            raise ValueError("binding IDs must be unique")
        for binding in self.bindings:
            if binding.resolution is not ResolutionState.RESOLVED:
                raise ValueError("unresolved bindings belong to partial proposals")
            if isinstance(binding.value, MissionTargetValue) and (
                binding.value.target_role is not self.target.role
            ):
                raise ValueError("Mission target role mismatch; no implicit target mapping")
        for token in self.invocation.arguments:
            if isinstance(token, OptionValueToken | PositionalToken | BindingToken) and (
                token.binding_id not in bindings
                or bindings[token.binding_id].channel is not DeliveryChannel.ARGUMENT
            ):
                raise ValueError("argument token requires an argument-channel binding")
        names = tuple(item.name for item in self.environment)
        if len(set(names)) != len(names):
            raise ValueError("environment allowlist names must be unique")
        for item in self.environment:
            if item.binding_id not in bindings or (
                bindings[item.binding_id].channel is not DeliveryChannel.ENVIRONMENT
            ):
                raise ValueError("environment entry requires an environment-channel binding")
        for requirement in self.sensitive_requirements:
            sensitive_binding = bindings.get(requirement.binding_id)
            if sensitive_binding is None:
                raise ValueError("sensitive requirement needs an associated binding")
            value = sensitive_binding.value
            if isinstance(requirement, SecretRequirement):
                if not isinstance(value, SecretValue) or value.secret_ref != requirement.secret_ref:
                    raise ValueError("secret requirement and binding disagree")
            elif not isinstance(value, CredentialValue) or (
                value.credential_ref != requirement.credential_ref
            ):
                raise ValueError("credential requirement and binding disagree")
        required_bindings = {item.binding_id for item in self.sensitive_requirements}
        if any(
            isinstance(item.value, SecretValue | CredentialValue)
            and item.binding_id not in required_bindings
            for item in self.bindings
        ):
            raise ValueError("sensitive bindings require explicit purpose/role requirements")
        for ids in (
            tuple(item.dependency_id for item in self.dependencies),
            tuple(item.requirement_id for item in self.resources),
            tuple(item.requirement_id for item in self.sessions),
            tuple(item.evidence_id for item in self.expected_evidence),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError("requirement/evidence IDs must be unique")
        if any(
            rule.endpoint_binding_id is not None and rule.endpoint_binding_id not in bindings
            for rule in self.network.rules
        ):
            raise ValueError("network endpoint references an undeclared binding")
        resource_ids = {item.requirement_id for item in self.resources}
        if any(
            item.resource_requirement_id is not None
            and item.resource_requirement_id not in resource_ids
            for item in self.sessions
        ):
            raise ValueError("Session requirement must refer to a declared Resource requirement")
        evidence_ids = {item.evidence_id for item in self.expected_evidence}
        if any(not set(item.evidence_ids) <= evidence_ids for item in self.expected_results):
            raise ValueError("expected results require declared evidence identities")
        return self


type ExecutionPlanDocument = ExecutionPlan | ExecutionPlanV2


def decode_execution_plan(payload: str | bytes) -> ExecutionPlanDocument:
    """Decode legacy (including unversioned M1 data) or v2; reject unknown versions.

    Deserialization never confers executor eligibility or execution permission.
    """
    return TypeAdapter(ExecutionPlanDocument).validate_json(payload)


def execution_intent_digest(plan: ExecutionPlanV2) -> str:
    """Semantic identity, not a signature. Nonsemantic generated ID/time are excluded."""
    return canonical_digest(plan, exclude=frozenset({"execution_plan_id", "created_at"}))
