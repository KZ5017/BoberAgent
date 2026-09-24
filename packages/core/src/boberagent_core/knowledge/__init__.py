"""Deterministic, file-backed reusable Knowledge services owned by Core."""

from .markdown import CuratedMarkdownLoader, KnowledgeSourceError
from .models import (
    KnowledgeDocument,
    KnowledgeId,
    KnowledgeSourceKind,
    KnowledgeStatus,
    MarkdownHeading,
    ProcedureDefinition,
    ProcedureId,
    ProcedureStep,
    SourceProvenance,
)
from .procedures import ProcedureRegistry
from .repository import KnowledgeConflict, KnowledgeRepository
from .router import (
    KnowledgeRequest,
    KnowledgeResolution,
    KnowledgeRoute,
    KnowledgeRouter,
    UnsupportedKnowledgeRoute,
)

__all__ = [
    "CuratedMarkdownLoader",
    "KnowledgeConflict",
    "KnowledgeDocument",
    "KnowledgeId",
    "KnowledgeRepository",
    "KnowledgeRequest",
    "KnowledgeResolution",
    "KnowledgeRoute",
    "KnowledgeRouter",
    "KnowledgeSourceError",
    "KnowledgeSourceKind",
    "KnowledgeStatus",
    "MarkdownHeading",
    "ProcedureDefinition",
    "ProcedureId",
    "ProcedureRegistry",
    "ProcedureStep",
    "SourceProvenance",
    "UnsupportedKnowledgeRoute",
]
