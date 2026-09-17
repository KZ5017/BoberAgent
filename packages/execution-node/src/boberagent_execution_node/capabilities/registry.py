"""Node-local capability provider registry and lazy implementation loading."""

from __future__ import annotations

import importlib
from enum import StrEnum
from pathlib import Path

from boberagent_contracts import CapabilityDefinition
from boberagent_sdk import Capability
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CapabilityAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class CapabilityManifest(BaseModel):
    """Static metadata plus lazy Python entry points."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: CapabilityDefinition
    implementation: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
    input_models: dict[str, str]

    @model_validator(mode="after")
    def match_operations(self) -> CapabilityManifest:
        operations = {operation.name for operation in self.definition.operations}
        if set(self.input_models) != operations:
            raise ValueError("input_models must define exactly one entry point per operation")
        return self


class CapabilityProvider:
    """A validated provider whose implementation remains lazy until execution."""

    def __init__(self, manifest: CapabilityManifest, manifest_path: Path) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.availability = CapabilityAvailability.AVAILABLE
        self.failure: str | None = None
        self.availability_reason: str | None = None
        self._implementation: Capability | None = None

    @property
    def definition(self) -> CapabilityDefinition:
        return self.manifest.definition

    def load_implementation(self) -> Capability:
        if self._implementation is not None:
            return self._implementation
        try:
            symbol = _load_symbol(self.manifest.implementation)
            if not isinstance(symbol, type) or not issubclass(symbol, Capability):
                raise TypeError("implementation entry point is not a Capability class")
            implementation = symbol()
            if implementation.capability_id != self.definition.capability_id:
                raise ValueError("implementation capability_id does not match manifest")
        except Exception as error:
            self.availability = CapabilityAvailability.UNAVAILABLE
            self.failure = f"{type(error).__name__}: {error}"
            raise CapabilityLoadError(
                f"could not load {self.definition.capability_id}: {type(error).__name__}"
            ) from error
        self._implementation = implementation
        return implementation

    def load_input_model(self, operation: str) -> type[BaseModel]:
        try:
            entrypoint = self.manifest.input_models[operation]
        except KeyError as error:
            raise CapabilityLoadError(f"unknown operation input model: {operation}") from error
        try:
            symbol = _load_symbol(entrypoint)
            if not isinstance(symbol, type) or not issubclass(symbol, BaseModel):
                raise TypeError("input-model entry point is not a Pydantic model class")
            return symbol
        except Exception as error:
            self.availability = CapabilityAvailability.UNAVAILABLE
            self.failure = f"{type(error).__name__}: {error}"
            raise CapabilityLoadError(
                f"could not load input model for {self.definition.capability_id}: "
                f"{type(error).__name__}"
            ) from error

    def apply_dependency_availability(
        self, *, missing_required: bool, missing_optional: bool
    ) -> None:
        """Reflect static dependency health without importing implementation code."""

        if missing_required:
            self.availability = CapabilityAvailability.UNAVAILABLE
            self.availability_reason = "one or more required local dependencies are unavailable"
        elif missing_optional:
            self.availability = CapabilityAvailability.DEGRADED
            self.availability_reason = "one or more optional local dependencies are unavailable"
        else:
            self.availability = CapabilityAvailability.AVAILABLE
            self.availability_reason = None


class CapabilityLoadError(RuntimeError):
    pass


class LocalCapabilityRegistry:
    """What this node can execute locally; distinct from Core's registry."""

    def __init__(self) -> None:
        self._providers: dict[str, CapabilityProvider] = {}
        self.failures: list[str] = []

    def register(self, provider: CapabilityProvider) -> None:
        capability_id = str(provider.definition.capability_id)
        if capability_id in self._providers:
            message = f"duplicate capability ID rejected: {capability_id}"
            self.failures.append(message)
            raise ValueError(message)
        self._providers[capability_id] = provider

    def get(self, capability_id: str) -> CapabilityProvider:
        try:
            return self._providers[capability_id]
        except KeyError as error:
            raise CapabilityLoadError(
                f"capability is not installed locally: {capability_id}"
            ) from error

    def definitions(self) -> tuple[CapabilityDefinition, ...]:
        return tuple(
            self._providers[key].definition
            for key in sorted(self._providers)
            if self._providers[key].availability is not CapabilityAvailability.DISABLED
        )

    def providers(self) -> tuple[CapabilityProvider, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))


def _load_symbol(entrypoint: str) -> object:
    module_name, separator, attribute = entrypoint.partition(":")
    if not separator:
        raise ValueError("entry point must use 'module:attribute'")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)
