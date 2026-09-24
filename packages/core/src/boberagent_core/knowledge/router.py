"""Core-facing deterministic Knowledge routing, without M18/M19 fallbacks."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from boberagent_core.models import CoreModel

from .markdown import CuratedMarkdownLoader
from .models import (
    KnowledgeDocument,
    KnowledgeId,
    KnowledgeStatus,
    ProcedureDefinition,
    ProcedureId,
)
from .procedures import ProcedureRegistry
from .repository import KnowledgeConflict, KnowledgeRepository


class UnsupportedKnowledgeRoute(ValueError):
    """A requested semantic or external route is deliberately unavailable in M17."""


class KnowledgeRoute(StrEnum):
    PROCEDURE_ID = "PROCEDURE_ID"
    KNOWLEDGE_ID = "KNOWLEDGE_ID"
    STRUCTURED = "STRUCTURED"


class KnowledgeRequest(CoreModel):
    procedure_id: ProcedureId | None = None
    knowledge_id: KnowledgeId | None = None
    version: int | None = Field(default=None, gt=0)
    goal_type: str | None = None
    environment: str | None = None
    technology: str | None = None
    required_state: str | None = None
    produced_state: str | None = None
    capability_id: str | None = None
    domain: str | None = None
    protocol: str | None = None
    tool: str | None = None
    status: KnowledgeStatus = KnowledgeStatus.CANONICAL
    semantic_query: str | None = None
    requires_current_external: bool = False

    @model_validator(mode="after")
    def unambiguous_identity(self) -> Self:
        if self.procedure_id is not None and self.knowledge_id is not None:
            raise ValueError("request may specify only one exact identity")
        if self.version is not None and self.procedure_id is None and self.knowledge_id is None:
            raise ValueError("version requires an explicit Knowledge or Procedure ID")
        return self


class KnowledgeResolution(CoreModel):
    route: KnowledgeRoute
    procedures: tuple[ProcedureDefinition, ...] = ()
    documents: tuple[KnowledgeDocument, ...] = ()


class KnowledgeRouter:
    """Only public Core lookup gateway for maintained reusable Knowledge."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        procedures: ProcedureRegistry,
        *,
        source_root: Path | None = None,
        known_capability_ids: frozenset[str] | None = None,
    ) -> None:
        self.repository = repository
        self.procedures = procedures
        self._source_root = source_root
        self._known_capability_ids = known_capability_ids
        self._validate_references()

    @classmethod
    def from_directory(
        cls,
        root: Path,
        *,
        known_capability_ids: frozenset[str] | None = None,
    ) -> KnowledgeRouter:
        loader = CuratedMarkdownLoader(root)
        repository = KnowledgeRepository.from_directory(loader)
        procedures = ProcedureRegistry.from_directory(
            loader, known_capability_ids=known_capability_ids
        )
        return cls(
            repository,
            procedures,
            source_root=root,
            known_capability_ids=known_capability_ids,
        )

    def reload(self) -> KnowledgeRouter:
        """Build a fully validated new snapshot; leave this snapshot untouched on failure."""

        if self._source_root is None:
            raise ValueError("router was not created from a source directory")
        return self.from_directory(
            self._source_root, known_capability_ids=self._known_capability_ids
        )

    def lookup_procedure(
        self, procedure_id: ProcedureId, *, version: int | None = None
    ) -> ProcedureDefinition | None:
        return self.procedures.get(procedure_id, version=version)

    def get_canonical(self, knowledge_id: KnowledgeId) -> KnowledgeDocument | None:
        return self.repository.get(knowledge_id)

    def resolve(self, request: KnowledgeRequest) -> KnowledgeResolution:
        if request.requires_current_external:
            raise UnsupportedKnowledgeRoute("external research is not available in M17")
        if request.procedure_id is not None:
            procedure = self.procedures.get(request.procedure_id, version=request.version)
            return KnowledgeResolution(
                route=KnowledgeRoute.PROCEDURE_ID,
                procedures=(procedure,) if procedure is not None else (),
            )
        if request.knowledge_id is not None:
            document = self.repository.get(request.knowledge_id, version=request.version)
            return KnowledgeResolution(
                route=KnowledgeRoute.KNOWLEDGE_ID,
                documents=(document,) if document is not None else (),
            )
        if request.semantic_query is not None:
            raise UnsupportedKnowledgeRoute("semantic retrieval belongs to M18")
        fields = (
            request.goal_type,
            request.environment,
            request.technology,
            request.required_state,
            request.produced_state,
            request.capability_id,
            request.domain,
            request.protocol,
            request.tool,
        )
        if not any(field is not None for field in fields):
            raise ValueError("structured Knowledge lookup requires at least one metadata filter")
        procedures = self.procedures.find(
            status=request.status,
            goal_type=request.goal_type,
            environment=request.environment,
            technology=request.technology,
            required_state=request.required_state,
            produced_state=request.produced_state,
            capability_id=request.capability_id,
        )
        documents = self.repository.list_documents(
            status=request.status,
            domain=request.domain,
            technology=request.technology,
            protocol=request.protocol,
            tool=request.tool,
            capability_id=request.capability_id,
        )
        if any(
            field is not None
            for field in (
                request.goal_type,
                request.environment,
                request.required_state,
                request.produced_state,
            )
        ):
            documents = ()
        if any(field is not None for field in (request.domain, request.protocol, request.tool)):
            procedures = ()
        return KnowledgeResolution(
            route=KnowledgeRoute.STRUCTURED,
            procedures=procedures,
            documents=documents,
        )

    def _validate_references(self) -> None:
        for document in self.repository.list_documents(status=None):
            for related in document.related_knowledge_ids:
                if not self.repository.versions(related):
                    raise KnowledgeConflict(
                        f"{document.knowledge_id} references unknown Knowledge: {related}"
                    )
            for related_procedure in document.procedure_ids:
                if not self.procedures.versions(related_procedure):
                    raise KnowledgeConflict(
                        f"{document.knowledge_id} references unknown Procedure: {related_procedure}"
                    )
        for procedure in self.procedures.find(status=None):
            for related in procedure.related_knowledge_ids:
                if not self.repository.versions(related):
                    raise KnowledgeConflict(
                        f"{procedure.procedure_id} references unknown Knowledge: {related}"
                    )
