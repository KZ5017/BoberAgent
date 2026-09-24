"""Immutable, Core-owned reusable Knowledge and Procedure definitions."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from boberagent_contracts import CapabilityId, OperationName
from boberagent_contracts.refs import DomainRef
from pydantic import AwareDatetime, Field, model_validator

from boberagent_core.models import CoreModel


class KnowledgeId(DomainRef):
    """Stable identity of reusable explanatory Knowledge, never a file path."""

    def __new__(cls, value: str) -> Self:
        if not value.startswith("knowledge.") or len(value) <= len("knowledge."):
            raise ValueError("KnowledgeId must start with 'knowledge.'")
        return super().__new__(cls, value)


class ProcedureId(DomainRef):
    """Stable identity of authoritative operational guidance."""

    def __new__(cls, value: str) -> Self:
        if not value.startswith("procedure.") or len(value) <= len("procedure."):
            raise ValueError("ProcedureId must start with 'procedure.'")
        return super().__new__(cls, value)


class KnowledgeStatus(StrEnum):
    DRAFT = "DRAFT"
    CANONICAL = "CANONICAL"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class KnowledgeSourceKind(StrEnum):
    AUTHOR_MAINTAINED = "author_maintained"
    PROJECT_DOCUMENTATION = "project_documentation"
    VENDOR_DOCUMENTATION = "vendor_documentation"
    TOOL_DOCUMENTATION = "tool_documentation"
    RESEARCH_PUBLICATION = "research_publication"
    ASSESSMENT_DERIVED_CURATED_NOTE = "assessment_derived_curated_note"


class SourceProvenance(CoreModel):
    """Curated source location and exact loaded revision, not Mission evidence."""

    kind: KnowledgeSourceKind
    source_path: str = Field(min_length=1)
    source_uri: str | None = None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MarkdownHeading(CoreModel):
    """Document structure retained for navigation, not a semantic chunk."""

    level: int = Field(ge=1, le=6)
    title: str = Field(min_length=1)
    path: tuple[str, ...] = Field(min_length=1)
    line_number: int = Field(ge=1)


class KnowledgeDocument(CoreModel):
    knowledge_id: KnowledgeId
    version: int = Field(gt=0)
    title: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: KnowledgeStatus
    domains: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    technology: str | None = None
    platform: str | None = None
    protocol: str | None = None
    tool: str | None = None
    capability_ids: tuple[CapabilityId, ...] = ()
    procedure_ids: tuple[ProcedureId, ...] = ()
    related_knowledge_ids: tuple[KnowledgeId, ...] = ()
    version_applicability: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    provenance: SourceProvenance
    body: str = Field(min_length=1)
    headings: tuple[MarkdownHeading, ...] = ()


class ProcedureStep(CoreModel):
    """One recommended Capability action; inputs and execution belong to Workflow."""

    step_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
    capability_id: CapabilityId
    operation: OperationName
    purpose: str = Field(min_length=1)


class ProcedureDefinition(CoreModel):
    procedure_id: ProcedureId
    version: int = Field(gt=0)
    title: str = Field(min_length=1)
    status: KnowledgeStatus
    goal_type: str = Field(min_length=1)
    environment: str | None = None
    technology: str | None = None
    required_state: tuple[str, ...] = ()
    produced_state: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    completion_conditions: tuple[str, ...] = Field(min_length=1)
    coverage_requirements: tuple[str, ...] = ()
    fallbacks: tuple[str, ...] = ()
    known_failure_modes: tuple[str, ...] = ()
    steps: tuple[ProcedureStep, ...] = Field(min_length=1)
    related_knowledge_ids: tuple[KnowledgeId, ...] = ()
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    provenance: SourceProvenance
    body: str = Field(min_length=1)
    headings: tuple[MarkdownHeading, ...] = ()

    @model_validator(mode="after")
    def unique_step_ids(self) -> Self:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Procedure step IDs must be unique")
        return self

    @property
    def candidate_capability_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(step.capability_id for step in self.steps))
