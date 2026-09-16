"""Immutable evidence-derived Observation model."""

from pydantic import AwareDatetime, Field

from ._base import FrozenContractModel, JsonValue, SymbolicName
from .refs import ArtifactRef, CapabilityRunRef, DomainRef, ObservationRef


class Observation(FrozenContractModel):
    """An immutable fact observed or deterministically derived from evidence."""

    observation_id: ObservationRef
    type: SymbolicName
    subject_ref: DomainRef | None = None
    value: JsonValue
    run_ref: CapabilityRunRef
    observed_at: AwareDatetime
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: tuple[ArtifactRef, ...] = ()
