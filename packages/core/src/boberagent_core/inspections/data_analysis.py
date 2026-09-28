"""Declarative data and attributed documentation; strings never become commands."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Literal

from .extraction import FileExtractor, ParserCoverageError, safe_name
from .lexical_analysis import _mask_comments
from .semantic_models import (
    BehaviorKind,
    DependencyKind,
    DependencyObservation,
    EntrypointCandidate,
    Requirement,
    RequirementKind,
    SourceFact,
)

_SIMPLE_REQUIREMENT = re.compile(
    r"([A-Za-z][A-Za-z0-9_.-]{0,127})(\[[A-Za-z0-9_,.-]+\])?\s*((?:(?:==|>=|<=|!=|~=|>|<)\s*[0-9][A-Za-z0-9.*+_-]*(?:\s*,\s*)?)*\s*)"
)
_PYTHON_VERSION = re.compile(r"(?:[<>=!~]{0,2}\s*\d+(?:\.\d+){0,2}\s*,?\s*)+")


def _dependency(extractor: FileExtractor, value: str, start: int, end: int) -> None:
    if len(value) > 512:
        extractor.unknown(start, end, "UNSUPPORTED_REQUIREMENT_SYNTAX")
        return
    match = _SIMPLE_REQUIREMENT.fullmatch(value.strip())
    if match is None:
        extractor.unknown(start, end, "UNSUPPORTED_REQUIREMENT_SYNTAX")
        return
    constraint = match.group(3).strip()
    if len(constraint) > 128:
        extractor.unknown(start, end, "UNSUPPORTED_REQUIREMENT_SYNTAX")
        return
    extractor.items.add(
        DependencyObservation(
            **extractor.evidence(start, end, "DECLARED_DEPENDENCY", match.group(1)),
            kind=DependencyKind.DECLARED_PACKAGE,
            name=match.group(1),
            version_constraint=constraint or None,
        )
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate property")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-JSON constant")


def analyze_data(extractor: FileExtractor) -> None:
    text = extractor.decoded.text
    basename = extractor.path.rsplit("/", 1)[-1].lower()
    if basename == "requirements.txt":
        offset = 0
        for line in text.splitlines(keepends=True):
            value = line.strip()
            if value and not value.startswith("#"):
                start = offset + len(line) - len(line.lstrip())
                end = start + len(value)
                _dependency(extractor, value, start, end)
            offset += len(line)
        return
    try:
        if basename.endswith(".json"):
            json.loads(text, object_pairs_hook=_unique, parse_constant=_reject_constant)
        else:
            tomllib.loads(text)
    except (ValueError, RecursionError) as error:
        raise ParserCoverageError("DECLARATIVE_PARSE_FAILED") from error
    # We intentionally do not echo arbitrary fields, commands or string values.
    first = next((index for index, char in enumerate(text) if not char.isspace()), None)
    if first is not None:
        extractor.items.add(
            SourceFact(
                **extractor.evidence(first, first + 1, "DECLARATIVE_PARSE_SUCCEEDED"),
                kind="DECLARATIVE_DATA",
            )
        )
    if basename != "pyproject.toml":
        extractor.items.gap(extractor.path, extractor.origin, "GENERIC_DATA_NO_SCHEMA")
        return
    if '"""' in text or "\x27\x27\x27" in text:
        extractor.items.gap(extractor.path, extractor.origin, "UNSUPPORTED_METADATA_LOCATION")
        return
    data = tomllib.loads(text)
    # Ignore comments while retaining original character offsets for citations.
    text = _mask_comments(text, powershell=False)
    project = data.get("project")
    if not isinstance(project, dict):
        return
    # This bounded subset handles ordinary literal PEP 621 declarations. More
    # complex valid TOML remains a coverage gap, never a guessed source locator.
    section = re.search(r"(?m)^\[project\]\s*$", text)
    if section is None:
        extractor.items.gap(extractor.path, extractor.origin, "UNSUPPORTED_METADATA_LOCATION")
        return
    next_section = re.search(r"(?m)^\[", text[section.end() :])
    project_end = section.end() + next_section.start() if next_section else len(text)
    body = text[section.end() : project_end]
    runtime = project.get("requires-python")
    if isinstance(runtime, str):
        match = re.search(r"(?m)^\s*requires-python\s*=\s*([\"'])([^\n\"']*)\1", body)
        if (
            match
            and match.group(2) == runtime
            and len(runtime) <= 128
            and _PYTHON_VERSION.fullmatch(runtime)
        ):
            start, end = section.end() + match.start(2), section.end() + match.end(2)
            extractor.items.add(
                Requirement(
                    **extractor.evidence(start, end, "DECLARED_PYTHON_REQUIREMENT"),
                    kind=RequirementKind.RUNTIME,
                    name=runtime,
                )
            )
        else:
            extractor.items.gap(extractor.path, extractor.origin, "UNSUPPORTED_RUNTIME_DECLARATION")
    dependencies = project.get("dependencies")
    if isinstance(dependencies, list):
        block = re.search(r"(?ms)^\s*dependencies\s*=\s*\[([^\[\]]*)\]", body)
        if block is None:
            extractor.items.gap(
                extractor.path, extractor.origin, "UNSUPPORTED_DEPENDENCY_DECLARATION"
            )
        else:
            found: set[str] = set()
            for match in re.finditer(r"([\"'])([^\n\"']+)\1", block.group(1)):
                value = match.group(2)
                if value in dependencies:
                    found.add(value)
                    start = section.end() + block.start(1) + match.start(2)
                    _dependency(extractor, value, start, start + len(value))
            if any(not isinstance(value, str) or value not in found for value in dependencies):
                extractor.items.gap(
                    extractor.path, extractor.origin, "UNSUPPORTED_DEPENDENCY_DECLARATION"
                )
    scripts = project.get("scripts")
    if isinstance(scripts, dict):
        block = re.search(r"(?m)^\[project\.scripts\]\s*$", text)
        if block:
            next_section = re.search(r"(?m)^\[", text[block.end() :])
            end = block.end() + next_section.start() if next_section else len(text)
            for match in re.finditer(
                r"(?m)^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*=", text[block.end() : end]
            ):
                name = match.group(1)
                if name in scripts and safe_name(name):
                    start = block.end() + match.start(1)
                    extractor.items.add(
                        EntrypointCandidate(
                            **extractor.evidence(
                                start, start + len(name), "DECLARED_SCRIPT_CANDIDATE", name
                            ),
                            runtime="python",
                            invocation_style="DECLARED_SCRIPT",
                        )
                    )
                    extractor.indicator(start, start + len(name), BehaviorKind.DECLARED_SCRIPT)


def analyze_documentation(extractor: FileExtractor) -> None:
    text = extractor.decoded.text
    offset = 0
    for line in text.splitlines(keepends=True):
        extractor.items.check_time()
        runtime = re.search(
            r"\b(?:requires?|needs?)\s+Python\s+([0-9]+(?:\.[0-9]+){0,2})\b", line, re.IGNORECASE
        )
        if runtime:
            extractor.items.add(
                Requirement(
                    **extractor.evidence(
                        offset + runtime.start(), offset + runtime.end(), "DOCUMENTED_RUNTIME_CLAIM"
                    ),
                    kind=RequirementKind.RUNTIME,
                    name=runtime.group(1),
                )
            )
        for word, kind in (
            ("listener", RequirementKind.LISTENER),
            ("root", RequirementKind.PRIVILEGE),
            ("administrator", RequirementKind.PRIVILEGE),
            ("credentials", RequirementKind.CREDENTIAL),
        ):
            match = re.search(
                r"\b(?:requires?|needs?)\s+(?:an?\s+)?" + word + r"\b", line, re.IGNORECASE
            )
            if match:
                extractor.items.add(
                    Requirement(
                        **extractor.evidence(
                            offset + match.start(),
                            offset + match.end(),
                            "DOCUMENTED_PREREQUISITE_CLAIM",
                            word,
                        ),
                        kind=kind,
                        name=word,
                    )
                )
        match = re.search(r"\bno credentials required\b", line, re.IGNORECASE)
        if match:
            extractor.items.add(
                SourceFact(
                    **extractor.evidence(
                        offset + match.start(),
                        offset + match.end(),
                        "DOCUMENTED_NEGATIVE_CREDENTIAL_CLAIM",
                    ),
                    kind="DOCUMENTED_NO_CREDENTIALS",
                )
            )
        labels: tuple[tuple[str, Literal["DOCUMENTED_USAGE", "DOCUMENTED_TARGET"]], ...] = (
            (r"\b(?:usage|run)\s*:", "DOCUMENTED_USAGE"),
            (r"\btarget\s*:", "DOCUMENTED_TARGET"),
        )
        for pattern, fact_kind in labels:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                extractor.items.add(
                    SourceFact(
                        **extractor.evidence(
                            offset + match.start(),
                            offset + match.end(),
                            "DOCUMENTATION_LABEL",
                            kind,
                        ),
                        kind=fact_kind,
                    )
                )
        match = re.search(
            r"\b(?:requires?|needs?)\s+(requests|aiohttp|click)\b", line, re.IGNORECASE
        )
        if match:
            extractor.items.add(
                DependencyObservation(
                    **extractor.evidence(
                        offset + match.start(),
                        offset + match.end(),
                        "DOCUMENTED_DEPENDENCY_CLAIM",
                        match.group(1).lower(),
                    ),
                    kind=DependencyKind.DOCUMENTED_DEPENDENCY,
                    name=match.group(1).lower(),
                )
            )
        offset += len(line)
