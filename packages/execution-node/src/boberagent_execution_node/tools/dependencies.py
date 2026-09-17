"""Capability dependency evaluation without installation side effects."""

from boberagent_contracts import CapabilityDefinition, DependencyType
from boberagent_sdk import DependencyError
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

from boberagent_execution_node.capabilities.registry import (
    CapabilityLoadError,
    LocalCapabilityRegistry,
)

from .registry import ToolAvailability, ToolRegistry


class DependencyReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    available: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()

    @property
    def satisfied(self) -> bool:
        return not self.missing_required


class DependencyResolver:
    def __init__(self, tools: ToolRegistry, capabilities: LocalCapabilityRegistry) -> None:
        self._tools = tools
        self._capabilities = capabilities

    def evaluate(self, definition: CapabilityDefinition) -> DependencyReport:
        available: list[str] = []
        required: list[str] = []
        optional: list[str] = []
        for dependency in definition.dependencies:
            label = f"{dependency.dependency_type.value}:{dependency.identifier}"
            satisfied = self._satisfied(
                dependency.dependency_type,
                dependency.identifier,
                dependency.version_spec,
            )
            if satisfied:
                available.append(label)
            elif dependency.required:
                required.append(label)
            else:
                optional.append(label)
        return DependencyReport(
            available=tuple(available),
            missing_required=tuple(required),
            missing_optional=tuple(optional),
        )

    def require(self, definition: CapabilityDefinition) -> DependencyReport:
        report = self.evaluate(definition)
        if not report.satisfied:
            raise DependencyError(
                "required local dependencies unavailable: " + ", ".join(report.missing_required)
            )
        return report

    def _satisfied(
        self, dependency_type: DependencyType, identifier: str, version_spec: str | None
    ) -> bool:
        if dependency_type is DependencyType.TOOL:
            try:
                record = self._tools.get(identifier)
            except KeyError:
                return False
            if record.availability is not ToolAvailability.AVAILABLE:
                return False
            return _version_satisfies(record.version, version_spec)
        if dependency_type is DependencyType.CAPABILITY:
            try:
                provider = self._capabilities.get(identifier)
            except CapabilityLoadError:
                return False
            return _version_satisfies(provider.definition.implementation_version, version_spec)
        return False


def _version_satisfies(version: str | None, specification: str | None) -> bool:
    if specification is None:
        return True
    if version is None:
        return False
    try:
        return Version(version) in SpecifierSet(specification)
    except (InvalidSpecifier, InvalidVersion):
        return False
