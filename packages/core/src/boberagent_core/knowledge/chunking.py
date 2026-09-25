"""Source-faithful Markdown sections with contextualized embedding input."""

from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256
from typing import TYPE_CHECKING, Literal
from uuid import NAMESPACE_URL, uuid5

from .models import (
    KnowledgeDocument,
    KnowledgeId,
    MarkdownHeading,
    ProcedureDefinition,
    ProcedureId,
)

if TYPE_CHECKING:
    from .semantic import SemanticChunk

CHUNKING_VERSION = "section-blocks-v1"
EMBEDDING_INPUT_VERSION = "title-heading-body-v1"
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST = re.compile(r"^ {0,3}(?:[-*+]|\d+[.)])[ \t]+")
_TABLE = re.compile(r"^\s*\|")


def _line_offsets(body: str) -> list[int]:
    offsets = [0]
    for line in body.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _blocks(body: str, start: int, end: int) -> list[tuple[int, int]]:
    """Separate paragraph, list, table, and fenced-code runs at exact source offsets."""

    spans: list[tuple[int, int]] = []
    cursor = start
    block_start: int | None = None
    block_end = start
    block_kind: str | None = None
    fence_char: str | None = None
    fence_length = 0
    while cursor < end:
        newline = body.find("\n", cursor, end)
        line_end = end if newline < 0 else newline + 1
        line = body[cursor:line_end]
        marker = _FENCE.match(line)
        if fence_char is not None:
            kind: str | None = "code"
            if marker is not None:
                fence = marker.group(1)
                if fence[0] == fence_char and len(fence) >= fence_length:
                    fence_char = None
        elif marker is not None:
            fence = marker.group(1)
            fence_char, fence_length = fence[0], len(fence)
            kind = "code"
        elif not line.strip():
            kind = None
        elif _LIST.match(line) or (block_kind == "list" and line[:1].isspace()):
            kind = "list"
        elif _TABLE.match(line):
            kind = "table"
        else:
            kind = "paragraph"
        if kind is None:
            if block_start is not None:
                spans.append((block_start, block_end))
                block_start = None
            block_kind = None
        else:
            if block_start is not None and kind != block_kind:
                spans.append((block_start, block_end))
                block_start = None
            if block_start is None:
                block_start = cursor
            block_end = line_end
            block_kind = kind
        cursor = line_end
    if block_start is not None:
        spans.append((block_start, block_end))
    return spans


def _hard_split(body: str, start: int, end: int, maximum: int) -> list[tuple[int, int]]:
    pieces: list[tuple[int, int]] = []
    while start < end:
        stop = min(start + maximum, end)
        if stop < end:
            line_break = body.rfind("\n", start + 1, stop)
            if line_break > start:
                stop = line_break + 1
        pieces.append((start, stop))
        start = stop
    return pieces


def _section_spans(
    body: str, headings: tuple[MarkdownHeading, ...]
) -> list[tuple[int, tuple[str, ...], int, int, int]]:
    offsets = _line_offsets(body)
    starts = [offsets[heading.line_number - 1] for heading in headings]
    ends = [offsets[heading.line_number] for heading in headings]
    sections: list[tuple[int, tuple[str, ...], int, int, int]] = []
    occurrences: dict[tuple[str, ...], int] = defaultdict(int)
    if not headings:
        return [(0, (), 0, 0, len(body))]
    if starts[0] > 0:
        sections.append((0, (), 0, 0, starts[0]))
    for ordinal, heading in enumerate(headings, 1):
        occurrence = occurrences[heading.path]
        occurrences[heading.path] += 1
        sections.append(
            (
                ordinal,
                heading.path,
                occurrence,
                ends[ordinal - 1],
                starts[ordinal] if ordinal < len(headings) else len(body),
            )
        )
    return sections


def chunk_source(
    source: KnowledgeDocument | ProcedureDefinition,
    *,
    target_chars: int = 1800,
    hard_max_chars: int = 4000,
) -> tuple[SemanticChunk, ...]:
    """Chunk governed body only; headings remain context, never standalone evidence."""

    from .semantic import SemanticChunk  # Avoid a module-initialization cycle.

    if target_chars < 1 or hard_max_chars < target_chars:
        raise ValueError("invalid structural chunk size bounds")
    source_ref: KnowledgeId | ProcedureId
    source_type: Literal["reference", "procedure"]
    if isinstance(source, ProcedureDefinition):
        source_ref = source.procedure_id
        source_type = "procedure"
        kind = "procedure"
        domains: tuple[str, ...] = ()
        tags: tuple[str, ...] = ()
        platform = None
        protocol = None
        tool = None
        capability_ids = source.candidate_capability_ids
        procedure_ids: tuple[ProcedureId, ...] = (source.procedure_id,)
        version_applicability = None
        goal_type = source.goal_type
        environment = source.environment
        required_state = source.required_state
        produced_state = source.produced_state
    else:
        source_ref = source.knowledge_id
        source_type = "reference"
        kind = source.kind
        domains = source.domains
        tags = source.tags
        platform = source.platform
        protocol = source.protocol
        tool = source.tool
        capability_ids = tuple(source.capability_ids)
        procedure_ids = source.procedure_ids
        version_applicability = source.version_applicability
        goal_type = None
        environment = None
        required_state = ()
        produced_state = ()
    body = source.body
    result: list[SemanticChunk] = []
    for section_ordinal, path, occurrence, start, end in _section_spans(body, source.headings):
        units: list[tuple[int, int]] = []
        for block_start, block_end in _blocks(body, start, end):
            if block_end - block_start > hard_max_chars:
                units.extend(_hard_split(body, block_start, block_end, hard_max_chars))
            else:
                units.append((block_start, block_end))
        groups: list[tuple[int, int]] = []
        group_start: int | None = None
        group_end = start
        for unit_start, unit_end in units:
            if group_start is not None and unit_end - group_start > target_chars:
                groups.append((group_start, group_end))
                group_start = None
            if group_start is None:
                group_start = unit_start
            group_end = unit_end
        if group_start is not None:
            groups.append((group_start, group_end))
        for chunk_ordinal, (chunk_start, chunk_end) in enumerate(groups):
            source_text = body[chunk_start:chunk_end]
            if not source_text.strip():
                continue
            heading_context = " > ".join(path) if path else "(document introduction)"
            embedding_text = (
                f"Title: {source.title}\nSection: {heading_context}\n\n{source_text.strip()}"
            )
            identity = (
                f"{source_ref}:{source.version}:{CHUNKING_VERSION}:"
                f"{path!r}:{occurrence}:{chunk_ordinal}"
            )
            result.append(
                SemanticChunk(
                    chunk_id=str(uuid5(NAMESPACE_URL, identity)),
                    source_ref=source_ref,
                    source_type=source_type,
                    version=source.version,
                    source_sha256=source.provenance.content_sha256,
                    provenance=source.provenance,
                    title=source.title,
                    heading_path=path,
                    heading_occurrence=occurrence,
                    section_ordinal=section_ordinal,
                    chunk_ordinal=chunk_ordinal,
                    document_ordinal=len(result),
                    char_start=chunk_start,
                    char_end=chunk_end,
                    source_text=source_text,
                    embedding_text=embedding_text,
                    content_sha256=sha256(source_text.encode("utf-8")).hexdigest(),
                    chunking_version=CHUNKING_VERSION,
                    embedding_input_version=EMBEDDING_INPUT_VERSION,
                    kind=kind,
                    status=source.status,
                    domains=domains,
                    tags=tags,
                    technology=source.technology,
                    platform=platform,
                    protocol=protocol,
                    tool=tool,
                    capability_ids=capability_ids,
                    procedure_ids=procedure_ids,
                    version_applicability=version_applicability,
                    goal_type=goal_type,
                    environment=environment,
                    required_state=required_state,
                    produced_state=produced_state,
                )
            )
    return tuple(result)
