"""Local end-to-end semantic discovery remains derived from curated M17 sources."""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from boberagent_core.knowledge import (
    EmbeddingBatch,
    KnowledgeId,
    KnowledgeRequest,
    KnowledgeRoute,
    KnowledgeRouter,
    ProcedureId,
    SemanticIndexIncompatible,
    SemanticIndexStale,
    SemanticRetrievalService,
    SemanticUnavailable,
)
from boberagent_core.knowledge.qdrant_local import QdrantSemanticIndex


class FakeEmbeddingProvider:
    provider_id = "deterministic-test"
    max_batch_size = 2

    def __init__(self, model_id: str = "keywords-v1", *, dimension: int = 3) -> None:
        self.model_id = model_id
        self.dimension = dimension
        self.fail = False
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic provider outage")
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            lowered = text.lower()
            if "alphabetical" in lowered:
                vector = (0.0, 0.0, 1.0)
            elif "directory" in lowered:
                vector = (1.0, 0.0, 0.0)
            else:
                vector = (0.0, 1.0, 0.0)
            vectors.append(vector[: self.dimension] + (0.0,) * max(0, self.dimension - 3))
        return EmbeddingBatch(
            provider_id=self.provider_id,
            model_id=self.model_id,
            vectors=tuple(vectors),
            dimension=self.dimension,
        )


def _reference(identity: str, *, title: str, domain: str, body: str) -> str:
    return (
        "+++\n"
        f'id = "knowledge.{identity}"\n'
        "version = 1\n"
        f'title = "{title}"\n'
        'type = "reference"\n'
        'status = "CANONICAL"\n'
        'source_kind = "author_maintained"\n'
        f'domains = ["{domain}"]\n'
        'tags = ["signing"]\n'
        'technology = "directory"\n'
        'platform = "linux"\n'
        'version_applicability = "v1"\n'
        "+++\n"
        f"{body}"
    )


def _corpus(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    root = vault / "BOBER_AGENT"
    (root / "reference").mkdir(parents=True)
    (root / "procedures").mkdir()
    (vault / "unrelated-note.md").write_text(
        _reference("outside", title="Outside", domain="identity", body="# Directory\nOutside.\n"),
        encoding="utf-8",
    )
    (root / "reference" / "a.md").write_text(
        _reference(
            "a_directory",
            title="Directory signing",
            domain="identity",
            body=(
                "# Directory\nDirectory authentication binds a request.\n\n"
                "## Signing\nDirectory signing verifies integrity.\n\n"
                "## Signing\nDirectory signing is also relevant to replay.\n"
            ),
        ),
        encoding="utf-8",
    )
    (root / "reference" / "b.md").write_text(
        _reference(
            "b_filtered",
            title="Directory signing",
            domain="web",
            body="# Directory\nDirectory signing in web context.\n",
        ),
        encoding="utf-8",
    )
    (root / "reference" / "c.md").write_text(
        _reference(
            "c_decoy",
            title="Alphabetical signing",
            domain="identity",
            body="# Alphabetical\nAlphabetical signing labels are not authentication.\n",
        ),
        encoding="utf-8",
    )
    return root


def _router(
    root: Path, index: QdrantSemanticIndex, provider: FakeEmbeddingProvider
) -> KnowledgeRouter:
    return KnowledgeRouter.from_directory(
        root,
        semantic_service=SemanticRetrievalService(root=root, provider=provider, index=index),
    )


def test_local_qdrant_router_provenance_filters_ties_and_exact_precedence(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    index = QdrantSemanticIndex(tmp_path / "derived-index")
    provider = FakeEmbeddingProvider()
    try:
        router = _router(root, index, provider)
        assert router.get_canonical(KnowledgeId("knowledge.outside")) is None
        with pytest.raises(SemanticUnavailable, match="not been built"):
            router.resolve(KnowledgeRequest(semantic_query="directory"))
        assert router.refresh_semantic()
        assert not router.refresh_semantic()
        hits = router.resolve(KnowledgeRequest(semantic_query="directory", domain="identity"))
        assert hits.route is KnowledgeRoute.SEMANTIC
        assert hits.semantic_hits
        assert all(str(hit.chunk.source_ref) != "knowledge.outside" for hit in hits.semantic_hits)
        assert all(
            str(hit.chunk.source_ref) != "knowledge.b_filtered" for hit in hits.semantic_hits
        )
        assert hits.semantic_hits[0].chunk.source_ref == KnowledgeId("knowledge.a_directory")
        assert hits.semantic_hits[0].score > 0.9  # Qdrant cosine similarity.
        constrained = router.resolve(
            KnowledgeRequest(
                semantic_query="directory",
                domain="identity",
                kind="reference",
                tag="signing",
                platform="linux",
                version_applicability="v1",
            )
        )
        assert constrained.semantic_hits
        assert not router.resolve(
            KnowledgeRequest(semantic_query="directory", platform="windows")
        ).semantic_hits

        chunks = [
            hit.chunk
            for hit in hits.semantic_hits
            if str(hit.chunk.source_ref) == "knowledge.a_directory"
        ]
        assert [chunk.document_ordinal for chunk in chunks] == sorted(
            chunk.document_ordinal for chunk in chunks
        )
        assert [
            chunk.heading_occurrence
            for chunk in chunks
            if chunk.heading_path == ("Directory", "Signing")
        ] == [0, 1]
        assert all(chunk.provenance.source_path == "reference/a.md" for chunk in chunks)
        assert all(chunk.source_sha256 == chunks[0].source_sha256 for chunk in chunks)
        document = router.get_canonical(KnowledgeId("knowledge.a_directory"))
        assert document is not None
        assert all(
            chunk.source_text == document.body[chunk.char_start : chunk.char_end]
            for chunk in chunks
        )

        calls = provider.calls
        provider.fail = True
        exact = router.resolve(
            KnowledgeRequest(
                knowledge_id=KnowledgeId("knowledge.a_directory"), semantic_query="directory"
            )
        )
        assert exact.route is KnowledgeRoute.KNOWLEDGE_ID
        assert provider.calls == calls
        assert (
            router.resolve(KnowledgeRequest(domain="identity")).route is KnowledgeRoute.STRUCTURED
        )
        with pytest.raises(RuntimeError, match="outage"):
            router.resolve(KnowledgeRequest(semantic_query="directory"))
    finally:
        index.close()


def test_refresh_reopen_staleness_deletion_and_generation_failure(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    index_root = tmp_path / "derived-index"
    provider = FakeEmbeddingProvider()
    index = QdrantSemanticIndex(index_root)
    router = _router(root, index, provider)
    try:
        assert router.refresh_semantic()
        first_manifest = index.manifest()
        assert first_manifest is not None and first_manifest.chunk_count >= 4
        source = root / "reference" / "a.md"
        source.write_text(
            source.read_text(encoding="utf-8") + "\nAnother directory detail.\n", encoding="utf-8"
        )
        changed = router.reload()
        with pytest.raises(SemanticIndexStale):
            changed.resolve(KnowledgeRequest(semantic_query="directory"))
        provider.fail = True
        with pytest.raises(RuntimeError, match="outage"):
            changed.refresh_semantic()
        assert index.manifest() == first_manifest
        provider.fail = False
        assert changed.refresh_semantic()
        assert index.manifest() != first_manifest
        (root / "reference" / "b.md").unlink()
        deleted = changed.reload()
        with pytest.raises(SemanticIndexStale):
            deleted.resolve(KnowledgeRequest(semantic_query="directory"))
        assert deleted.refresh_semantic()
        assert all(
            str(hit.chunk.source_ref) != "knowledge.b_filtered"
            for hit in deleted.resolve(KnowledgeRequest(semantic_query="directory")).semantic_hits
        )
    finally:
        index.close()

    reopened = QdrantSemanticIndex(index_root)
    try:
        loaded = _router(root, reopened, provider)
        assert loaded.resolve(KnowledgeRequest(semantic_query="directory")).semantic_hits
        other_model = _router(root, reopened, FakeEmbeddingProvider(model_id="keywords-v2"))
        with pytest.raises(SemanticIndexIncompatible):
            other_model.resolve(KnowledgeRequest(semantic_query="directory"))
    finally:
        reopened.close()


def test_source_relocation_refreshes_provenance_without_changing_chunk_ids(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    index = QdrantSemanticIndex(tmp_path / "derived-index")
    try:
        router = _router(root, index, FakeEmbeddingProvider())
        router.refresh_semantic()
        before = router.resolve(KnowledgeRequest(semantic_query="directory", domain="identity"))
        (root / "reference" / "a.md").rename(root / "reference" / "renamed.md")
        moved = router.reload()
        with pytest.raises(SemanticIndexStale):
            moved.resolve(KnowledgeRequest(semantic_query="directory"))
        moved.refresh_semantic()
        after = moved.resolve(KnowledgeRequest(semantic_query="directory", domain="identity"))
        first_ids = [
            hit.chunk.chunk_id
            for hit in before.semantic_hits
            if str(hit.chunk.source_ref) == "knowledge.a_directory"
        ]
        second = [
            hit.chunk
            for hit in after.semantic_hits
            if str(hit.chunk.source_ref) == "knowledge.a_directory"
        ]
        assert first_ids == [chunk.chunk_id for chunk in second]
        assert all(chunk.provenance.source_path == "reference/renamed.md" for chunk in second)
    finally:
        index.close()


def test_existing_procedure_narrative_is_discoverable_not_executed(tmp_path: Path) -> None:
    root = tmp_path / "curated"
    (root / "reference").mkdir(parents=True)
    (root / "procedures").mkdir()
    shipped = Path(__file__).resolve().parents[3] / "knowledge"
    shutil.copyfile(
        shipped / "reference" / "network-service-evidence.md", root / "reference" / "evidence.md"
    )
    shutil.copyfile(
        shipped / "procedures" / "network-service-discovery.md",
        root / "procedures" / "procedure.md",
    )
    index = QdrantSemanticIndex(tmp_path / "derived-index")
    try:
        router = _router(root, index, FakeEmbeddingProvider())
        router.refresh_semantic()
        result = router.resolve(KnowledgeRequest(semantic_query="network"))
        assert any(hit.chunk.source_type == "procedure" for hit in result.semantic_hits)
        procedure_hits = [
            hit for hit in result.semantic_hits if hit.chunk.source_type == "procedure"
        ]
        assert procedure_hits[0].chunk.heading_path
        assert procedure_hits[0].chunk.source_ref == "procedure.network.service_discovery"
        linked = router.resolve(
            KnowledgeRequest(
                semantic_query="network",
                procedure_filter=ProcedureId("procedure.network.service_discovery"),
            )
        )
        assert linked.semantic_hits
        assert all(
            ProcedureId("procedure.network.service_discovery") in hit.chunk.procedure_ids
            for hit in linked.semantic_hits
        )
    finally:
        index.close()


def test_provider_dimension_change_requires_and_permits_explicit_refresh(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    provider = FakeEmbeddingProvider()
    index = QdrantSemanticIndex(tmp_path / "derived-index")
    try:
        router = _router(root, index, provider)
        assert router.refresh_semantic()
        old_manifest = index.manifest()
        assert old_manifest is not None and old_manifest.dimension == 3
        provider.dimension = 4
        with pytest.raises(SemanticIndexIncompatible, match="dimension"):
            router.resolve(KnowledgeRequest(semantic_query="directory"))
        assert router.refresh_semantic()
        new_manifest = index.manifest()
        assert new_manifest is not None and new_manifest.dimension == 4
        assert router.resolve(KnowledgeRequest(semantic_query="directory")).semantic_hits
    finally:
        index.close()
