"""Qdrant-local adapter guards dimensions, identities, filtering, and persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_core.knowledge import (
    CHUNKING_VERSION,
    EMBEDDING_INPUT_VERSION,
    IndexManifest,
    KnowledgeId,
    KnowledgeRouter,
    SemanticFilters,
    SemanticIndexIncompatible,
    SemanticUnavailable,
    chunk_source,
)
from boberagent_core.knowledge.qdrant_local import QdrantSemanticIndex


def _manifest(chunk_count: int, *, dimension: int = 2) -> IndexManifest:
    return IndexManifest(
        index_format_version=1,
        provider_id="test-provider",
        model_id="test-model",
        dimension=dimension,
        chunking_version=CHUNKING_VERSION,
        embedding_input_version=EMBEDDING_INPUT_VERSION,
        source_root_digest="explicit-root",
        source_revisions={},
        chunk_count=chunk_count,
        created_at=datetime.now(UTC),
    )


def test_qdrant_local_rejects_bad_vectors_and_persists_filtered_points(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[3] / "knowledge"
    source = KnowledgeRouter.from_directory(source_root).get_canonical(
        KnowledgeId("knowledge.network.service_evidence")
    )
    assert source is not None
    chunk = chunk_source(source)[0]
    index_root = tmp_path / "semantic"
    index = QdrantSemanticIndex(index_root)
    try:
        with pytest.raises(ValueError, match="count"):
            index.replace_generation(_manifest(2), [(chunk, (1.0, 0.0))])
        with pytest.raises(SemanticIndexIncompatible, match="dimensions"):
            index.replace_generation(_manifest(1), [(chunk, (1.0,))])
        with pytest.raises(ValueError, match="duplicate"):
            index.replace_generation(_manifest(2), [(chunk, (1.0, 0.0)), (chunk, (1.0, 0.0))])
        index.replace_generation(_manifest(1), [(chunk, (1.0, 0.0))])
        assert (
            len(index.search((1.0, 0.0), filters=SemanticFilters(domain="network"), limit=1)) == 1
        )
        assert not index.search((1.0, 0.0), filters=SemanticFilters(domain="web"), limit=1)
        with pytest.raises(SemanticIndexIncompatible):
            index.search((1.0,), filters=SemanticFilters(), limit=1)
    finally:
        index.close()
    reopened = QdrantSemanticIndex(index_root)
    try:
        assert reopened.manifest() is not None
        hit = reopened.search((1.0, 0.0), filters=SemanticFilters(), limit=1)[0]
        assert hit.chunk.chunk_id == chunk.chunk_id
        assert hit.chunk.provenance == chunk.provenance
    finally:
        reopened.close()


def test_empty_generation_and_unbuilt_index_are_distinct(tmp_path: Path) -> None:
    index = QdrantSemanticIndex(tmp_path / "semantic")
    try:
        with pytest.raises(SemanticUnavailable):
            index.search((1.0, 0.0), filters=SemanticFilters(), limit=1)
        index.replace_generation(_manifest(0), [])
        assert index.search((1.0, 0.0), filters=SemanticFilters(), limit=1) == ()
    finally:
        index.close()
