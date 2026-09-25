"""Exact, file-backed canonical Knowledge lookup with no Mission data path."""

from __future__ import annotations

from collections.abc import Iterable

from .markdown import CuratedMarkdownLoader, KnowledgeSourceError
from .models import KnowledgeDocument, KnowledgeId, KnowledgeStatus, ProcedureId


class KnowledgeConflict(KnowledgeSourceError):
    """An identity/version or current-canonical declaration conflicts."""


class KnowledgeRepository:
    """Immutable snapshot; reloading builds a fresh validated snapshot atomically."""

    def __init__(self, documents: Iterable[KnowledgeDocument]) -> None:
        by_version: dict[tuple[KnowledgeId, int], KnowledgeDocument] = {}
        canonical: dict[KnowledgeId, KnowledgeDocument] = {}
        for document in documents:
            key = document.knowledge_id, document.version
            if key in by_version:
                raise KnowledgeConflict(f"duplicate Knowledge identity/version: {key}")
            by_version[key] = document
            if document.status is KnowledgeStatus.CANONICAL:
                if document.knowledge_id in canonical:
                    raise KnowledgeConflict(
                        f"multiple current canonical versions: {document.knowledge_id}"
                    )
                canonical[document.knowledge_id] = document
        self._by_version = by_version
        self._canonical = canonical

    @classmethod
    def from_directory(cls, loader: CuratedMarkdownLoader) -> KnowledgeRepository:
        return cls(loader.load_reference(path) for path in loader.files("reference"))

    def get(
        self, knowledge_id: KnowledgeId, *, version: int | None = None
    ) -> KnowledgeDocument | None:
        """Current canonical by default; explicit versions include historical items."""

        if version is None:
            return self._canonical.get(knowledge_id)
        return self._by_version.get((knowledge_id, version))

    def list_documents(
        self,
        *,
        status: KnowledgeStatus | None = KnowledgeStatus.CANONICAL,
        domain: str | None = None,
        technology: str | None = None,
        protocol: str | None = None,
        tool: str | None = None,
        capability_id: str | None = None,
        procedure_id: ProcedureId | None = None,
        kind: str | None = None,
        tag: str | None = None,
        platform: str | None = None,
        version_applicability: str | None = None,
    ) -> tuple[KnowledgeDocument, ...]:
        values = (
            self._by_version.values()
            if status is None
            else (item for item in self._by_version.values() if item.status is status)
        )
        return tuple(
            sorted(
                (
                    item
                    for item in values
                    if (domain is None or domain in item.domains)
                    and (technology is None or item.technology == technology)
                    and (protocol is None or item.protocol == protocol)
                    and (tool is None or item.tool == tool)
                    and (capability_id is None or capability_id in item.capability_ids)
                    and (procedure_id is None or procedure_id in item.procedure_ids)
                    and (kind is None or item.kind == kind)
                    and (tag is None or tag in item.tags)
                    and (platform is None or item.platform == platform)
                    and (
                        version_applicability is None
                        or item.version_applicability == version_applicability
                    )
                ),
                key=lambda item: (item.knowledge_id, item.version),
            )
        )

    def versions(self, knowledge_id: KnowledgeId) -> tuple[KnowledgeDocument, ...]:
        return tuple(
            sorted(
                (
                    item
                    for (item_id, _), item in self._by_version.items()
                    if item_id == knowledge_id
                ),
                key=lambda item: item.version,
            )
        )
