"""Assessment-induced Effect records."""

from pydantic import AwareDatetime, Field

from ._base import ContractModel, JsonObject, NonEmptyStr, SymbolicName
from .capability import CapabilityId
from .refs import ArtifactRef, CapabilityRunRef, DomainRef, EffectRef


class EffectReversibility(ContractModel):
    """Known cleanup and reversibility information for an Effect."""

    reversible: bool | None = None
    cleanup_required: bool = False
    cleanup_status: SymbolicName | None = None
    cleanup_capability_id: CapabilityId | None = None
    cleanup_inputs: JsonObject = Field(default_factory=dict)
    description: NonEmptyStr | None = None


class Effect(ContractModel):
    """An actual target-side or assessment-context change caused by execution."""

    effect_id: EffectRef
    type: SymbolicName
    action: SymbolicName
    run_ref: CapabilityRunRef
    occurred_at: AwareDatetime
    intentional: bool
    confirmed: bool
    subject_ref: DomainRef | None = None
    before_ref: DomainRef | None = None
    after_ref: DomainRef | None = None
    evidence_refs: tuple[ArtifactRef, ...] = ()
    reversibility: EffectReversibility = Field(default_factory=EffectReversibility)
    metadata: JsonObject = Field(default_factory=dict)
