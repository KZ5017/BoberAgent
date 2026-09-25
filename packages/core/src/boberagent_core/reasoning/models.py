"""Bounded, advisory reasoning data; none of these objects authorize execution."""

from __future__ import annotations

from enum import StrEnum

from boberagent_contracts import (
    AssetRef,
    CapabilityId,
    CapabilityRunRef,
    CredentialRef,
    JsonObject,
    MissionRef,
    ObservationRef,
    OperationName,
    SecretRef,
    ServiceRef,
)
from pydantic import Field, field_validator

from boberagent_core.knowledge import (
    KnowledgeId,
    KnowledgeStatus,
    ProcedureId,
    SemanticHit,
    SourceProvenance,
)
from boberagent_core.models import CoreModel, GoalRef, GoalStatus

PROMPT_VERSION = "bounded-interpretation-v2"


class EvidenceStrength(StrEnum):
    WEAK = "WEAK"
    MIXED = "MIXED"
    STRONG = "STRONG"
    UNKNOWN = "UNKNOWN"


class KnowledgeCitation(CoreModel):
    knowledge_id: KnowledgeId
    version: int = Field(gt=0)
    chunk_id: str | None = None


class ProcedureCitation(CoreModel):
    procedure_id: ProcedureId
    version: int = Field(gt=0)


class Hypothesis(CoreModel):
    statement: str = Field(min_length=1, max_length=1000)
    evidence_strength: EvidenceStrength
    uncertainty: str | None = Field(default=None, max_length=1000)


class InterpretationResult(CoreModel):
    """An interpretation of supplied evidence, never a canonical Observation."""

    summary: str = Field(min_length=1, max_length=2000)
    hypotheses: tuple[Hypothesis, ...] = ()
    evidence_strength: EvidenceStrength
    supporting_observation_refs: tuple[ObservationRef, ...] = ()
    supporting_knowledge: tuple[KnowledgeCitation, ...] = ()
    supporting_procedure: ProcedureCitation | None = None
    contradictions: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()


_SENSITIVE_INPUT_NAMES = frozenset(
    {"password", "passphrase", "secret", "token", "api_key", "private_key", "ntlm_hash"}
)


def _reject_sensitive_input_keys(value: JsonObject) -> JsonObject:
    """Never let an ordinary proposed input become a secret-material carrier."""

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(key, str):
                    lowered = key.lower()
                    reference_field = lowered.endswith(("_ref", "_refs"))
                    sensitive_field = any(
                        lowered == name
                        or lowered.startswith(f"{name}_")
                        or lowered.endswith(f"_{name}")
                        for name in _SENSITIVE_INPUT_NAMES
                    )
                    if sensitive_field and not reference_field:
                        raise ValueError(
                            "ActionProposal inputs may contain references, not secret material"
                        )
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return value


class ActionProposal(CoreModel):
    """A candidate operation and known inputs; explicitly not a CapabilityInvocation."""

    capability_id: CapabilityId
    operation: OperationName
    purpose: str = Field(min_length=1, max_length=1000)
    expected_information_gain: str = Field(min_length=1, max_length=1000)
    asset_ref: AssetRef | None = None
    service_ref: ServiceRef | None = None
    inputs: JsonObject
    supporting_observation_refs: tuple[ObservationRef, ...] = ()
    supporting_knowledge: tuple[KnowledgeCitation, ...] = ()
    supporting_procedure: ProcedureCitation | None = None
    secret_refs: tuple[SecretRef, ...] = ()
    credential_refs: tuple[CredentialRef, ...] = ()

    @field_validator("inputs")
    @classmethod
    def no_plaintext_secret_fields(cls, value: JsonObject) -> JsonObject:
        return _reject_sensitive_input_keys(value)


class StructuredReasoning(CoreModel):
    interpretation: InterpretationResult
    proposal: ActionProposal | None = None


class ReasoningSelection(CoreModel):
    """Caller-explicit, Mission-scoped context selection; never a database dump."""

    mission_ref: MissionRef
    goal_ref: GoalRef
    asset_ref: AssetRef
    observation_refs: tuple[ObservationRef, ...] = ()
    procedure_id: ProcedureId | None = None
    canonical_knowledge_ids: tuple[KnowledgeId, ...] = ()
    semantic_hits: tuple[SemanticHit, ...] = ()
    capability_ids: tuple[CapabilityId, ...] = ()
    attempt_run_refs: tuple[CapabilityRunRef, ...] = ()
    diagnostic_codes: tuple[str, ...] = ()
    max_content_chars: int = Field(default=12000, ge=1500, le=100000)


class GoalContext(CoreModel):
    goal_ref: GoalRef
    goal_type: str
    status: GoalStatus


class AssetContext(CoreModel):
    asset_ref: AssetRef
    kind: str
    primary_address: str


class ServiceContext(CoreModel):
    service_ref: ServiceRef
    asset_ref: AssetRef
    transport: str
    port: int
    state: str
    service: str | None
    product: str | None
    version: str | None
    provenance_refs: tuple[ObservationRef, ...]


class AttemptContext(CoreModel):
    run_ref: CapabilityRunRef
    capability_id: CapabilityId
    operation: OperationName
    status: str


class ProcedureContext(CoreModel):
    citation: ProcedureCitation
    title: str
    goal_type: str
    preconditions: tuple[str, ...]
    candidate_actions: tuple[str, ...]
    provenance: SourceProvenance


class KnowledgeFragment(CoreModel):
    citations: tuple[KnowledgeCitation, ...] = Field(min_length=1)
    title: str
    heading_path: tuple[str, ...]
    document_ordinal: int = Field(ge=0)
    source_text: str
    status: KnowledgeStatus
    provenance: SourceProvenance
    source_sha256: str
    semantic_score: float | None = None
    authority: str


class OperationContext(CoreModel):
    name: OperationName
    input_schema: JsonObject


class CapabilityContext(CoreModel):
    capability_id: CapabilityId
    title: str
    operations: tuple[OperationContext, ...]
    provider_ids: tuple[str, ...]


class ContextBudget(CoreModel):
    max_chars: int
    included_chars: int
    included_counts: dict[str, int]
    omitted_counts: dict[str, int]


class ReasoningContext(CoreModel):
    prompt_version: str = PROMPT_VERSION
    mission_ref: MissionRef
    goal: GoalContext
    asset: AssetContext
    services: tuple[ServiceContext, ...]
    observation_refs: tuple[ObservationRef, ...]
    procedure: ProcedureContext | None
    attempts: tuple[AttemptContext, ...]
    knowledge: tuple[KnowledgeFragment, ...]
    capabilities: tuple[CapabilityContext, ...]
    diagnostic_codes: tuple[str, ...]
    authority_order: tuple[str, ...] = (
        "goal",
        "world_state",
        "procedure",
        "attempts",
        "canonical_knowledge",
        "semantic_knowledge",
        "capabilities",
    )
    budget: ContextBudget


class ReasonerUsage(CoreModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class ReasonerGeneration[T: CoreModel](CoreModel):
    value: T
    provider_id: str
    model_id: str
    finish_reason: str
    usage: ReasonerUsage | None = None


class ReasoningAssessment(CoreModel):
    """Structured, explainable result. A validated proposal still needs a separate decision."""

    context: ReasoningContext
    generation: ReasonerGeneration[StructuredReasoning]
    proposal_validated: bool
