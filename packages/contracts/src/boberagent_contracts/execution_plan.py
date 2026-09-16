"""Structured execution intent for dynamic or previously unknown code."""

from pydantic import AwareDatetime, Field

from ._base import ContractModel, JsonObject, NonEmptyStr, SymbolicName
from .capability import DependencyDeclaration, SideEffectDeclaration
from .enums import ExecutionPlanStatus
from .refs import ArtifactRef, CapabilityRunRef, ExecutionPlanRef, ResourceRef


class IsolationRequirement(ContractModel):
    """Requested runtime isolation profile plus provider-neutral constraints."""

    profile: SymbolicName
    requirements: JsonObject = Field(default_factory=dict)


class ExecutionPlan(ContractModel):
    """Validated structured intent; this object does not execute anything."""

    execution_plan_id: ExecutionPlanRef
    source_artifact_ref: ArtifactRef
    status: ExecutionPlanStatus
    runtime_type: SymbolicName
    runtime_version: str | None = Field(default=None, min_length=1, max_length=255)
    isolation: IsolationRequirement
    dependencies: tuple[DependencyDeclaration, ...] = ()
    entrypoint: NonEmptyStr
    argument_bindings: JsonObject = Field(default_factory=dict)
    resource_refs: tuple[ResourceRef, ...] = ()
    expected_outcomes: tuple[SymbolicName, ...] = ()
    expected_effects: tuple[SideEffectDeclaration, ...] = ()
    uncertainties: tuple[NonEmptyStr, ...] = ()
    created_at: AwareDatetime
    created_by_run: CapabilityRunRef | None = None
    metadata: JsonObject = Field(default_factory=dict)
