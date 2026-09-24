"""Strict, deterministic Markdown/TOML front-matter loader for curated sources."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from .models import (
    KnowledgeDocument,
    MarkdownHeading,
    ProcedureDefinition,
    SourceProvenance,
)

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_FORBIDDEN_METADATA = frozenset(
    {
        "mission_ref",
        "observation_ref",
        "artifact_ref",
        "secret_ref",
        "credential_ref",
        "secret_value",
        "password",
        "token",
    }
)
_Document = TypeVar("_Document", KnowledgeDocument, ProcedureDefinition)


class KnowledgeSourceError(ValueError):
    """A curated source cannot safely become canonical Knowledge."""


class CuratedMarkdownLoader:
    """Load only explicitly maintained files beneath a configured repository root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def load_reference(self, path: Path) -> KnowledgeDocument:
        return self._load(path, KnowledgeDocument, identity_field="knowledge_id")

    def load_procedure(self, path: Path) -> ProcedureDefinition:
        return self._load(path, ProcedureDefinition, identity_field="procedure_id")

    def files(self, directory: str) -> tuple[Path, ...]:
        if directory not in {"reference", "procedures"}:
            raise KnowledgeSourceError(f"unsupported curated source directory: {directory}")
        source_dir = self.root / directory
        if not source_dir.is_dir():
            raise KnowledgeSourceError(f"curated source directory does not exist: {source_dir}")
        return tuple(sorted(source_dir.rglob("*.md")))

    def _load(
        self,
        path: Path,
        model_type: type[_Document],
        *,
        identity_field: str,
    ) -> _Document:
        resolved = path.resolve()
        source_directory = self.root / (
            "reference" if identity_field == "knowledge_id" else "procedures"
        )
        if (
            not resolved.is_relative_to(source_directory)
            or path.is_symlink()
            or not resolved.is_file()
        ):
            raise KnowledgeSourceError(f"source is not a regular file beneath {self.root}: {path}")
        try:
            raw = resolved.read_bytes()
            text = raw.decode("utf-8")
            metadata, body = _split_front_matter(text)
            if _FORBIDDEN_METADATA.intersection(metadata):
                raise KnowledgeSourceError("Mission/Secret metadata is not curated Knowledge")
            source_kind = metadata.pop("source_kind")
            source_uri = metadata.pop("source_uri", None)
            metadata[identity_field] = metadata.pop("id")
            if identity_field == "knowledge_id":
                metadata["kind"] = metadata.pop("type")
            metadata["status"] = str(metadata["status"]).upper()
            provenance = SourceProvenance.model_validate(
                {
                    "kind": source_kind,
                    "source_path": resolved.relative_to(self.root).as_posix(),
                    "source_uri": source_uri,
                    "content_sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
            return model_type.model_validate(
                {
                    **metadata,
                    "provenance": provenance,
                    "body": body,
                    "headings": _headings(body),
                }
            )
        except (
            OSError,
            UnicodeError,
            KeyError,
            TypeError,
            ValueError,
            tomllib.TOMLDecodeError,
            ValidationError,
        ) as error:
            raise KnowledgeSourceError(f"invalid curated source {path}: {error}") from error


def _split_front_matter(text: str) -> tuple[dict[str, object], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "+++":
        raise KnowledgeSourceError("TOML front matter must begin with '+++'")
    closing = next(
        (index for index, line in enumerate(lines[1:], 1) if line.strip() == "+++"), None
    )
    if closing is None:
        raise KnowledgeSourceError("TOML front matter has no closing '+++'")
    parsed = tomllib.loads("".join(lines[1:closing]))
    body = "".join(lines[closing + 1 :])
    if not body.strip():
        raise KnowledgeSourceError("curated Markdown body is empty")
    return parsed, body


def _headings(body: str) -> tuple[MarkdownHeading, ...]:
    headings: list[MarkdownHeading] = []
    path: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line_number, line in enumerate(body.splitlines(), 1):
        fence = _FENCE.match(line)
        if fence is not None:
            marker = fence.group(1)
            if fence_char is None:
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
            continue
        if fence_char is not None:
            continue
        match = _HEADING.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        if not title:
            continue
        path = path[: level - 1]
        path.append(title)
        headings.append(
            MarkdownHeading(level=level, title=title, path=tuple(path), line_number=line_number)
        )
    return tuple(headings)
