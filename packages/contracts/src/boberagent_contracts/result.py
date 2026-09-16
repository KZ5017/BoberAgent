"""Universal Capability result envelope."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from ._base import ContractModel, JsonObject, NonEmptyStr, SymbolicName
from .artifact import ArtifactDescriptor
from .diagnostic import Diagnostic
from .effect import Effect
from .enums import CapabilityOutcomeCategory, CapabilityRunStatus
from .finding import Finding
from .observation import Observation
from .refs import CapabilityRunRef
from .resource import ResourceDescriptor
from .session import SessionDescriptor


class CapabilityOutcome(ContractModel):
    """Assessment meaning kept separate from execution lifecycle status."""

    category: CapabilityOutcomeCategory
    code: SymbolicName | None = None
    summary: NonEmptyStr | None = None
    details: JsonObject = Field(default_factory=dict)


class CapabilityResult(ContractModel):
    """Universal envelope returned by a terminal CapabilityRun."""

    run_ref: CapabilityRunRef
    execution_status: CapabilityRunStatus
    outcome: CapabilityOutcome
    observations: tuple[Observation, ...] = ()
    findings: tuple[Finding, ...] = ()
    artifacts: tuple[ArtifactDescriptor, ...] = ()
    resources: tuple[ResourceDescriptor, ...] = ()
    sessions: tuple[SessionDescriptor, ...] = ()
    effects: tuple[Effect, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @model_validator(mode="after")
    def require_terminal_execution_status(self) -> Self:
        if not self.execution_status.is_terminal:
            raise ValueError("CapabilityResult execution_status must be terminal")
        return self
