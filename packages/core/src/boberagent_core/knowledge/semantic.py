"""Derived semantic discovery over explicitly curated Knowledge snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field

from boberagent_core.models import CoreModel

from .chunking import CHUNKING_VERSION, EMBEDDING_INPUT_VERSION, chunk_source
from .models import (
    KnowledgeId,
    KnowledgeStatus,
    ProcedureId,
    SourceProvenance,
)
from .procedures import ProcedureRegistry
from .repository import KnowledgeRepository

INDEX_FORMAT_VERSION = 1


class SemanticUnavailable(RuntimeError):
    """Semantic infrastructure is absent or unavailable; deterministic lookup remains usable."""


class SemanticIndexIncompatible(SemanticUnavailable):
    """The active derived generation belongs to a different embedding configuration."""


class SemanticIndexStale(SemanticUnavailable):
    """Canonical source revisions changed since the active generation was built."""


class EmbeddingError(RuntimeError):
    """Safe, typed provider failure without upstream response bodies."""


class EmbeddingConfigurationError(EmbeddingError):
    pass


class EmbeddingAuthenticationError(EmbeddingError):
    pass


class EmbeddingUnavailableError(EmbeddingError):
    pass


class EmbeddingResponseError(EmbeddingError):
    pass


class EmbeddingDimensionError(EmbeddingResponseError):
    pass


class EmbeddingBatch(CoreModel):
    provider_id: str
    model_id: str
    vectors: tuple[tuple[float, ...], ...]
    dimension: int = Field(gt=0)


class EmbeddingProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def max_batch_size(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch: ...


class SemanticChunk(CoreModel):
    """An exact body slice plus separately synthesized embedding context."""

    chunk_id: str
    source_ref: KnowledgeId | ProcedureId
    source_type: Literal["reference", "procedure"]
    version: int = Field(gt=0)
    source_sha256: str
    provenance: SourceProvenance
    title: str
    heading_path: tuple[str, ...]
    heading_occurrence: int = Field(ge=0)
    section_ordinal: int = Field(ge=0)
    chunk_ordinal: int = Field(ge=0)
    document_ordinal: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    source_text: str
    embedding_text: str
    content_sha256: str
    chunking_version: str
    embedding_input_version: str
    kind: str
    status: KnowledgeStatus
    domains: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    technology: str | None = None
    platform: str | None = None
    protocol: str | None = None
    tool: str | None = None
    capability_ids: tuple[str, ...] = ()
    procedure_ids: tuple[ProcedureId, ...] = ()
    version_applicability: str | None = None
    goal_type: str | None = None
    environment: str | None = None
    required_state: tuple[str, ...] = ()
    produced_state: tuple[str, ...] = ()


class SemanticFilters(CoreModel):
    status: KnowledgeStatus = KnowledgeStatus.CANONICAL
    kind: str | None = None
    domain: str | None = None
    tag: str | None = None
    technology: str | None = None
    platform: str | None = None
    protocol: str | None = None
    tool: str | None = None
    capability_id: str | None = None
    procedure_filter: ProcedureId | None = None
    version_applicability: str | None = None
    goal_type: str | None = None
    environment: str | None = None
    required_state: str | None = None
    produced_state: str | None = None

    def payload_values(self) -> dict[str, str]:
        mapping = {
            "status": self.status.value,
            "kind": self.kind,
            "domains": self.domain,
            "tags": self.tag,
            "technology": self.technology,
            "platform": self.platform,
            "protocol": self.protocol,
            "tool": self.tool,
            "capability_ids": self.capability_id,
            "procedure_ids": str(self.procedure_filter) if self.procedure_filter else None,
            "version_applicability": self.version_applicability,
            "goal_type": self.goal_type,
            "environment": self.environment,
            "required_state": self.required_state,
            "produced_state": self.produced_state,
        }
        return {key: value for key, value in mapping.items() if value is not None}


class SemanticHit(CoreModel):
    chunk: SemanticChunk
    score: float


class IndexManifest(CoreModel):
    index_format_version: int
    provider_id: str
    model_id: str
    dimension: int = Field(gt=0)
    chunking_version: str
    embedding_input_version: str
    source_root_digest: str
    source_revisions: dict[str, str]
    chunk_count: int = Field(ge=0)
    created_at: AwareDatetime


class SemanticIndex(Protocol):
    def manifest(self) -> IndexManifest | None: ...

    def replace_generation(
        self, manifest: IndexManifest, points: Sequence[tuple[SemanticChunk, tuple[float, ...]]]
    ) -> None: ...

    def search(
        self, vector: tuple[float, ...], *, filters: SemanticFilters, limit: int
    ) -> tuple[SemanticHit, ...]: ...

    def close(self) -> None: ...


class SemanticRetrievalService:
    """Rebuilds a derived generation; exact M17 stores remain authoritative."""

    def __init__(self, *, root: Path, provider: EmbeddingProvider, index: SemanticIndex) -> None:
        self.root_digest = sha256(str(root.resolve()).encode("utf-8")).hexdigest()
        self.provider = provider
        self.index = index

    @staticmethod
    def _sources(
        repository: KnowledgeRepository, procedures: ProcedureRegistry
    ) -> tuple[tuple[str, int, str], ...]:
        return tuple(
            sorted(
                (
                    (
                        str(item.knowledge_id),
                        item.version,
                        f"{item.provenance.content_sha256}:{item.provenance.source_path}",
                    )
                    for item in repository.list_documents()
                ),
            )
        ) + tuple(
            sorted(
                (
                    (
                        str(item.procedure_id),
                        item.version,
                        f"{item.provenance.content_sha256}:{item.provenance.source_path}",
                    )
                    for item in procedures.find()
                ),
            )
        )

    def _revisions(
        self, repository: KnowledgeRepository, procedures: ProcedureRegistry
    ) -> dict[str, str]:
        return {
            f"{identity}@{version}": digest
            for identity, version, digest in self._sources(repository, procedures)
        }

    def _check_batch(self, batch: EmbeddingBatch, expected: int) -> int:
        if (
            batch.provider_id != self.provider.provider_id
            or batch.model_id != self.provider.model_id
        ):
            raise EmbeddingResponseError("embedding provider/model identity changed")
        if len(batch.vectors) != expected or any(
            len(vector) != batch.dimension for vector in batch.vectors
        ):
            raise EmbeddingDimensionError("embedding batch has invalid vector count or dimension")
        if any(not isfinite(value) for vector in batch.vectors for value in vector):
            raise EmbeddingResponseError("embedding batch contains non-finite values")
        return batch.dimension

    def refresh(self, repository: KnowledgeRepository, procedures: ProcedureRegistry) -> bool:
        """Build a complete new generation; an old generation survives any build failure."""

        revisions = self._revisions(repository, procedures)
        old = self.index.manifest()
        if old is not None and self._compatible(old) and old.source_revisions == revisions:
            probe = self.provider.embed(["dimension probe"])
            if self._check_batch(probe, 1) == old.dimension:
                return False
        chunks: list[SemanticChunk] = []
        for item in repository.list_documents():
            chunks.extend(chunk_source(item))
        for procedure in procedures.find():
            chunks.extend(chunk_source(procedure))
        points: list[tuple[SemanticChunk, tuple[float, ...]]] = []
        dimension: int | None = None
        texts = [chunk.embedding_text for chunk in chunks]
        if not texts:
            texts = ["dimension probe"]
        for offset in range(0, len(texts), self.provider.max_batch_size):
            batch_texts = texts[offset : offset + self.provider.max_batch_size]
            batch = self.provider.embed(batch_texts)
            found = self._check_batch(batch, len(batch_texts))
            if dimension is not None and dimension != found:
                raise EmbeddingDimensionError("embedding dimension changed during index build")
            dimension = found
            for chunk, vector in zip(
                chunks[offset : offset + len(batch_texts)], batch.vectors, strict=False
            ):
                points.append((chunk, vector))
        if dimension is None:
            raise EmbeddingDimensionError("embedding provider supplied no dimension")
        manifest = IndexManifest(
            index_format_version=INDEX_FORMAT_VERSION,
            provider_id=self.provider.provider_id,
            model_id=self.provider.model_id,
            dimension=dimension,
            chunking_version=CHUNKING_VERSION,
            embedding_input_version=EMBEDDING_INPUT_VERSION,
            source_root_digest=self.root_digest,
            source_revisions=revisions,
            chunk_count=len(chunks),
            created_at=datetime.now(UTC),
        )
        self.index.replace_generation(manifest, points)
        return True

    def _compatible(self, manifest: IndexManifest) -> bool:
        return (
            manifest.index_format_version == INDEX_FORMAT_VERSION
            and manifest.provider_id == self.provider.provider_id
            and manifest.model_id == self.provider.model_id
            and manifest.chunking_version == CHUNKING_VERSION
            and manifest.embedding_input_version == EMBEDDING_INPUT_VERSION
            and manifest.source_root_digest == self.root_digest
        )

    def search(
        self,
        query: str,
        *,
        filters: SemanticFilters,
        limit: int,
        repository: KnowledgeRepository,
        procedures: ProcedureRegistry,
    ) -> tuple[SemanticHit, ...]:
        manifest = self.index.manifest()
        if manifest is None:
            raise SemanticUnavailable("semantic index has not been built")
        if not self._compatible(manifest):
            raise SemanticIndexIncompatible(
                "semantic index configuration differs; refresh required"
            )
        if manifest.source_revisions != self._revisions(repository, procedures):
            raise SemanticIndexStale("canonical Knowledge changed; refresh required")
        batch = self.provider.embed([query])
        dimension = self._check_batch(batch, 1)
        if dimension != manifest.dimension:
            raise SemanticIndexIncompatible("query vector dimension differs from active index")
        hits = self.index.search(batch.vectors[0], filters=filters, limit=limit)
        return tuple(
            sorted(
                hits,
                key=lambda hit: (
                    -hit.score,
                    str(hit.chunk.source_ref),
                    hit.chunk.version,
                    hit.chunk.document_ordinal,
                    hit.chunk.chunk_id,
                ),
            )[:limit]
        )
