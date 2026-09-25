"""Adjacent semantic hits regain source order without merging unrelated sources."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from boberagent_core.knowledge import KnowledgeId, KnowledgeRouter, SemanticHit, chunk_source
from boberagent_core.reasoning.context import _semantic_source_order

ROOT = Path(__file__).resolve().parents[3]


def test_ranked_related_hits_reorder_but_unrelated_source_stays_distinct() -> None:
    router = KnowledgeRouter.from_directory(ROOT / "knowledge")
    source = router.get_canonical(KnowledgeId("knowledge.network.service_evidence"))
    assert source is not None
    alternate_body = "A distinct curated source describes another service.\n"
    alternate = source.model_copy(
        update={
            "knowledge_id": KnowledgeId("knowledge.network.alternate"),
            "title": "Alternate service evidence",
            "body": alternate_body,
            "headings": (),
            "provenance": source.provenance.model_copy(
                update={
                    "source_path": "reference/alternate.md",
                    "content_sha256": sha256(alternate_body.encode()).hexdigest(),
                }
            ),
        }
    )
    primary = chunk_source(source)
    secondary = chunk_source(alternate)
    assert len(primary) >= 3 and len(secondary) == 1
    ranked = (
        SemanticHit(chunk=primary[2], score=0.99),
        SemanticHit(chunk=secondary[0], score=0.98),
        SemanticHit(chunk=primary[0], score=0.97),
        SemanticHit(chunk=primary[1], score=0.96),
    )

    ordered = _semantic_source_order(ranked)

    assert [hit.chunk.source_ref for hit in ordered] == [
        source.knowledge_id,
        source.knowledge_id,
        source.knowledge_id,
        alternate.knowledge_id,
    ]
    assert [hit.chunk.document_ordinal for hit in ordered[:3]] == [0, 1, 2]
    assert ordered[3].chunk.source_text == alternate_body
