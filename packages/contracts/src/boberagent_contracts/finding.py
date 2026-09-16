"""Assessment Finding model."""

from pydantic import AwareDatetime, Field

from ._base import ContractModel, JsonObject, NonEmptyStr, ShortStr, SymbolicName
from .refs import ArtifactRef, CapabilityRunRef, DomainRef, FindingRef, ObservationRef


class Finding(ContractModel):
    """A security-relevant interpretation supported by evidence."""

    finding_id: FindingRef
    type: SymbolicName
    title: ShortStr
    description: NonEmptyStr
    run_ref: CapabilityRunRef
    created_at: AwareDatetime
    subject_ref: DomainRef | None = None
    severity: SymbolicName | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    observation_refs: tuple[ObservationRef, ...] = ()
    evidence_refs: tuple[ArtifactRef, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)
