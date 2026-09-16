"""Static Capability and Operation definitions."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ._base import ContractModel, JsonObject, NonEmptyStr, ShortStr, SymbolicName
from .enums import (
    DependencyType,
    ExecutionDuration,
    ExecutionInteraction,
    ResultObjectType,
    RetrySemantics,
    SideEffectCategory,
    SideEffectLevel,
)
from .version import VersionString, supports_contract_version

type CapabilityId = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=255,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$",
    ),
]
type OperationName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$"),
]


class SchemaDeclaration(ContractModel):
    """An inline JSON Schema or a stable reference to one."""

    inline: JsonObject | None = None
    ref: NonEmptyStr | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> Self:
        if (self.inline is None) == (self.ref is None):
            raise ValueError("exactly one of 'inline' or 'ref' must be provided")
        return self


class ExecutionCharacteristics(ContractModel):
    """Shared execution behavior used for routing, policy, and audit."""

    duration: ExecutionDuration
    interaction: ExecutionInteraction
    asynchronous: Literal[True] = True
    supports_cancellation: bool = False
    supports_checkpointing: bool = False


class InteractionSurfaceDeclaration(ContractModel):
    """Execution surfaces a capability may use."""

    local_compute: bool
    target_network: bool
    internet_access: bool
    active_session: bool
    managed_resource: bool


class SideEffectDeclaration(ContractModel):
    """A possible side effect declared before execution."""

    category: SideEffectCategory
    level: SideEffectLevel
    description: NonEmptyStr | None = None


class DependencyDeclaration(ContractModel):
    """A capability, tool, runtime, or Resource requirement."""

    dependency_type: DependencyType
    identifier: SymbolicName
    version_spec: ShortStr | None = None
    required: bool = True


class OperationDefinition(ContractModel):
    """One action belonging to a coherent Capability."""

    name: OperationName
    title: ShortStr
    description: NonEmptyStr
    input_schema: SchemaDeclaration
    output_schema: SchemaDeclaration | None = None
    required_references: tuple[SymbolicName, ...] = ()
    result_types: tuple[ResultObjectType, ...] = ()
    retry_semantics: RetrySemantics
    execution_requirements: JsonObject = Field(default_factory=dict)


class CapabilityDefinition(ContractModel):
    """Static, discoverable metadata for a Capability implementation."""

    capability_id: CapabilityId
    contract_version: VersionString
    implementation_version: VersionString
    title: ShortStr
    description: NonEmptyStr
    operations: tuple[OperationDefinition, ...] = Field(min_length=1)
    execution: ExecutionCharacteristics
    interaction_surfaces: InteractionSurfaceDeclaration
    side_effects: tuple[SideEffectDeclaration, ...] = Field(min_length=1)
    dependencies: tuple[DependencyDeclaration, ...]

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if not supports_contract_version(self.contract_version):
            raise ValueError("unsupported Capability Contract major version")

        operation_names = [operation.name for operation in self.operations]
        if len(operation_names) != len(set(operation_names)):
            raise ValueError("operation names must be unique within a Capability")

        side_effect_categories = [declaration.category for declaration in self.side_effects]
        if len(side_effect_categories) != len(set(side_effect_categories)):
            raise ValueError("side-effect categories must be unique within a Capability")

        return self
