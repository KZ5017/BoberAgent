"""Execution Diagnostic model."""

from pydantic import AwareDatetime, Field

from ._base import ContractModel, JsonObject, NonEmptyStr, SymbolicName
from .enums import DiagnosticSeverity
from .refs import ArtifactRef, CapabilityRunRef


class Diagnostic(ContractModel):
    """Execution-related information that is not target state."""

    code: SymbolicName
    severity: DiagnosticSeverity
    message: NonEmptyStr
    occurred_at: AwareDatetime
    run_ref: CapabilityRunRef | None = None
    details: JsonObject = Field(default_factory=dict)
    artifact_refs: tuple[ArtifactRef, ...] = ()
