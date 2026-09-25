"""Structural chunks retain source text, hierarchy, and stable logical identities."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from boberagent_core.knowledge import (
    KnowledgeDocument,
    KnowledgeId,
    KnowledgeRouter,
    MarkdownHeading,
)
from boberagent_core.knowledge.chunking import chunk_source


def _document() -> KnowledgeDocument:
    root = Path(__file__).resolve().parents[3] / "knowledge"
    document = KnowledgeRouter.from_directory(root).get_canonical(
        KnowledgeId("knowledge.network.service_evidence")
    )
    assert document is not None
    return document


def test_nested_and_repeated_headings_are_context_not_standalone_chunks() -> None:
    body = (
        "# Parent\n"
        "Opening context.\n\n"
        "## Child\n"
        "First body paragraph.\n\n"
        "## Child\n"
        "Second body paragraph.\n"
    )
    headings = (
        MarkdownHeading(level=1, title="Parent", path=("Parent",), line_number=1),
        MarkdownHeading(level=2, title="Child", path=("Parent", "Child"), line_number=4),
        MarkdownHeading(level=2, title="Child", path=("Parent", "Child"), line_number=7),
    )
    source = _document().model_copy(update={"body": body, "headings": headings})
    chunks = chunk_source(source)
    assert len(chunks) == 3
    assert [chunk.heading_occurrence for chunk in chunks] == [0, 0, 1]
    assert chunks[1].chunk_id != chunks[2].chunk_id
    assert all(chunk.source_text.strip() not in {"# Parent", "## Child"} for chunk in chunks)
    assert all(
        source.body[chunk.char_start : chunk.char_end] == chunk.source_text for chunk in chunks
    )
    assert "Section: Parent > Child\n\nFirst body" in chunks[1].embedding_text
    assert "Section: Parent > Child\n\nSecond body" in chunks[2].embedding_text
    assert [chunk.document_ordinal for chunk in chunks] == [0, 1, 2]


def test_large_section_splits_on_blocks_then_hard_bound_with_context() -> None:
    body = "# Evidence\n" + "\n\n".join(["A" * 80, "B" * 80, "C" * 80]) + "\n"
    headings = (MarkdownHeading(level=1, title="Evidence", path=("Evidence",), line_number=1),)
    source = _document().model_copy(update={"body": body, "headings": headings})
    chunks = chunk_source(source, target_chars=100, hard_max_chars=120)
    assert len(chunks) == 3
    assert [chunk.chunk_ordinal for chunk in chunks] == [0, 1, 2]
    assert all("Section: Evidence" in chunk.embedding_text for chunk in chunks)
    assert all(
        source.body[chunk.char_start : chunk.char_end] == chunk.source_text for chunk in chunks
    )
    assert all(chunk.char_end - chunk.char_start <= 120 for chunk in chunks)

    long_source = source.model_copy(update={"body": "# Evidence\n" + "Z" * 300})
    hard = chunk_source(long_source, target_chars=100, hard_max_chars=120)
    assert len(hard) == 3
    assert all(chunk.char_end - chunk.char_start <= 120 for chunk in hard)
    assert all("Section: Evidence" in chunk.embedding_text for chunk in hard)


def test_chunk_id_is_path_independent_but_hash_and_offsets_are_separate() -> None:
    original = _document()
    original_chunks = chunk_source(original)
    moved = original.model_copy(
        update={
            "provenance": original.provenance.model_copy(
                update={"source_path": "reference/moved.md"}
            )
        }
    )
    assert [chunk.chunk_id for chunk in chunk_source(moved)] == [
        chunk.chunk_id for chunk in original_chunks
    ]
    changed_body = original.body.replace("An observed service", "A newly observed service")
    changed = original.model_copy(
        update={
            "body": changed_body,
            "provenance": original.provenance.model_copy(
                update={"content_sha256": sha256(changed_body.encode()).hexdigest()}
            ),
        }
    )
    changed_chunks = chunk_source(changed)
    assert changed_chunks[0].chunk_id == original_chunks[0].chunk_id
    assert changed_chunks[0].content_sha256 != original_chunks[0].content_sha256
    assert changed_chunks[0].source_sha256 != original_chunks[0].source_sha256
    assert changed_chunks[0].char_end != original_chunks[0].char_end


def test_paragraph_list_table_and_fenced_code_are_structural_units() -> None:
    body = (
        "# Section\n"
        "Introduction.\n"
        "- first\n- second\n"
        "| col | value |\n| --- | --- |\n"
        "```text\nprint(1)\n```\n"
        "Closing.\n"
    )
    heading = MarkdownHeading(level=1, title="Section", path=("Section",), line_number=1)
    source = _document().model_copy(update={"body": body, "headings": (heading,)})
    chunks = chunk_source(source, target_chars=25, hard_max_chars=100)
    assert len(chunks) == 5
    assert chunks[0].source_text == "Introduction.\n"
    assert chunks[1].source_text == "- first\n- second\n"
    assert chunks[2].source_text.startswith("| col |")
    assert chunks[3].source_text == "```text\nprint(1)\n```\n"
    assert chunks[4].source_text == "Closing.\n"
    assert all(body[chunk.char_start : chunk.char_end] == chunk.source_text for chunk in chunks)
