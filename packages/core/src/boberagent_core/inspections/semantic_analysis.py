"""C2 deterministic profile over C1-verified entries, with honest partial coverage."""

from __future__ import annotations

from typing import Literal

from .data_analysis import analyze_data, analyze_documentation
from .evidence import InspectionError, VerifiedSource
from .extraction import ExtractedItems, FileExtractor, ParserCoverageError, SemanticLimit, stable_id
from .lexical_analysis import analyze_lexical
from .python_analysis import analyze_python
from .semantic_models import (
    PROFILE_ID,
    CoverageStatus,
    FileCoverage,
    InspectionConflict,
    RequirementKind,
    SemanticInspectionDocument,
    SemanticInspectionLimits,
    SemanticItem,
    SourceOrigin,
)
from .text import TextCoverageError, decode_source


def _extractor(path: str) -> tuple[str | None, SourceOrigin]:
    name = path.rsplit("/", 1)[-1].lower()
    if (
        any(
            part.lower() in {"vendor", "node_modules", "__pycache__", ".venv", "dist", "build"}
            for part in path.split("/")
        )
        or ".generated." in name
        or ".min." in name
    ):
        return None, SourceOrigin.CODE
    if name.endswith(".py"):
        return "python-ast", SourceOrigin.CODE
    if name.endswith(".ps1"):
        return "powershell-lexical", SourceOrigin.CODE
    if name.endswith(".sh"):
        return "shell-lexical", SourceOrigin.CODE
    if name.startswith("readme") or name.endswith(".md"):
        return "documentation-claims", SourceOrigin.DOCUMENTATION
    if name == "requirements.txt" or name.endswith((".json", ".toml")):
        return "declarative-data", SourceOrigin.DECLARATIVE_METADATA
    return None, SourceOrigin.CODE


def _conflicts(items: ExtractedItems) -> tuple[InspectionConflict, ...]:
    result: list[InspectionConflict] = []
    pairs: list[
        tuple[
            Literal["RUNTIME_CLAIMS_DIFFER", "CREDENTIAL_CLAIMS_DIFFER"], SemanticItem, SemanticItem
        ]
    ] = []
    for doc in items.requirements:
        if doc.origin is not SourceOrigin.DOCUMENTATION or doc.kind is not RequirementKind.RUNTIME:
            continue
        for declared in items.requirements:
            if (
                declared.origin is SourceOrigin.DECLARATIVE_METADATA
                and declared.kind is RequirementKind.RUNTIME
                and declared.name != doc.name
            ):
                pairs.append(("RUNTIME_CLAIMS_DIFFER", doc, declared))
    for doc_fact in items.facts:
        if doc_fact.kind == "DOCUMENTED_NO_CREDENTIALS":
            for requirement in items.requirements:
                if (
                    requirement.origin is SourceOrigin.CODE
                    and requirement.kind is RequirementKind.CREDENTIAL
                ):
                    pairs.append(("CREDENTIAL_CLAIMS_DIFFER", doc_fact, requirement))
    for kind, first, second in pairs:
        if len(result) >= items.limits.max_conflicts:
            items.limit_reasons.add("CONFLICT_LIMIT")
            items.gap(first.source_path, first.origin, "CONFLICT_LIMIT")
            break
        result.append(
            InspectionConflict(
                conflict_id=stable_id("conflict-", [kind, first.item_id, second.item_id]),
                kind=kind,
                item_refs=(first.item_id, second.item_id),
                citations=(*first.citations, *second.citations),
            )
        )
    return tuple(result)


def analyze_semantics(source: VerifiedSource) -> SemanticInspectionDocument:
    inspection = source.inspection
    limits = inspection.limits
    if not isinstance(limits, SemanticInspectionLimits):
        raise InspectionError("INSPECTION_CONFIG_INVALID")
    if any(path not in source.entries for path in inspection.selected_paths):
        raise InspectionError("INSPECTION_CONFIG_INVALID")
    items = ExtractedItems(source, limits)
    coverage: list[FileCoverage] = []
    verified: set[str] = set()
    count, total = 0, 0
    for path, entry in sorted(source.entries.items()):
        extractor_id, origin = _extractor(path)
        status, reason = CoverageStatus.INSPECTED, "BOUNDED_EXTRACTOR_COMPLETED"
        encoding = None
        try:
            items.check_time()
        except SemanticLimit:
            status, reason = CoverageStatus.SKIPPED_LIMIT, "WALL_TIME_LIMIT"
        if status is CoverageStatus.INSPECTED:
            if entry.type != "file" or extractor_id is None:
                status, reason = (
                    CoverageStatus.SKIPPED_UNSUPPORTED_TYPE,
                    "UNSUPPORTED_OR_GENERATED_TYPE",
                )
            elif inspection.selected_paths and path not in inspection.selected_paths:
                status, reason = CoverageStatus.SKIPPED_LIMIT, "NOT_SELECTED_BY_PROFILE_CONFIG"
            elif count >= limits.max_semantic_files:
                status, reason = CoverageStatus.SKIPPED_LIMIT, "SEMANTIC_FILE_LIMIT"
            elif (entry.size_bytes or 0) > min(
                limits.max_semantic_bytes_per_file, limits.max_entry_bytes
            ):
                status, reason = CoverageStatus.SKIPPED_LIMIT, "SEMANTIC_PER_FILE_BYTES_LIMIT"
            elif total + (entry.size_bytes or 0) > min(
                limits.max_semantic_bytes_total, limits.max_total_verified_bytes
            ):
                status, reason = CoverageStatus.SKIPPED_LIMIT, "SEMANTIC_TOTAL_BYTES_LIMIT"
        if status is CoverageStatus.INSPECTED:
            count += 1
            try:
                content = source.verify_entry(path)
            except InspectionError as error:
                if error.code != "INSPECTION_LIMIT_EXCEEDED":
                    raise
                status, reason = CoverageStatus.SKIPPED_LIMIT, "WALL_TIME_LIMIT"
            else:
                verified.add(path)
                total += len(content)
                try:
                    decoded = decode_source(content)
                    encoding = decoded.encoding
                    if len(decoded.line_starts) > limits.max_lines_per_file:
                        raise SemanticLimit("SEMANTIC_LINE_LIMIT")
                    extractor = FileExtractor(
                        items, path, content, decoded, origin, extractor_id or PROFILE_ID
                    )
                    if extractor_id == "python-ast":
                        analyze_python(extractor)
                    elif extractor_id == "powershell-lexical":
                        analyze_lexical(extractor, powershell=True)
                    elif extractor_id == "shell-lexical":
                        analyze_lexical(extractor, powershell=False)
                    elif extractor_id == "documentation-claims":
                        analyze_documentation(extractor)
                    else:
                        analyze_data(extractor)
                    items.check_time()
                    if path in items.gap_paths:
                        status, reason = CoverageStatus.PARTIAL, "EXTRACTOR_LIMITATIONS"
                except TextCoverageError as error:
                    reason = error.code
                    status = (
                        CoverageStatus.SKIPPED_BINARY
                        if reason == "BINARY_CONTENT"
                        else CoverageStatus.SKIPPED_ENCODING
                    )
                except ParserCoverageError as error:
                    status, reason = CoverageStatus.PARSER_FAILED, str(error)
                except SemanticLimit as error:
                    status, reason = CoverageStatus.PARTIAL, error.code
        if status is not CoverageStatus.INSPECTED:
            if entry.type == "file":
                items.gap(path, origin, reason)
            if status in {CoverageStatus.SKIPPED_LIMIT, CoverageStatus.PARTIAL} and reason.endswith(
                "LIMIT"
            ):
                items.limit_reasons.add(reason)
        coverage.append(
            FileCoverage(
                path=path,
                size_bytes=entry.size_bytes,
                sha256=entry.sha256,
                status=status,
                reason=reason,
                extractor_id=extractor_id or "structural-only",
                encoding=encoding,
            )
        )
    if len(items.entrypoints) > 1:
        for candidate in items.entrypoints:
            items.gap(candidate.source_path, candidate.origin, "MULTIPLE_ENTRYPOINT_CANDIDATES")
    conflicts = _conflicts(items)
    coverage = [
        item.model_copy(
            update={"status": CoverageStatus.PARTIAL, "reason": "EXTRACTOR_LIMITATIONS"}
        )
        if item.status is CoverageStatus.INSPECTED and item.path in items.gap_paths
        else item
        for item in coverage
    ]
    return SemanticInspectionDocument(
        verified_paths=tuple(sorted(verified)),
        unverified_paths=tuple(sorted(set(source.entries) - verified)),
        citations=tuple(items.citations),
        facts=tuple(items.facts),
        entrypoint_candidates=tuple(items.entrypoints),
        parameter_candidates=tuple(items.parameters),
        dependency_observations=tuple(items.dependencies),
        requirements=tuple(items.requirements),
        behavior_indicators=tuple(items.behaviors),
        risk_indicators=tuple(items.risks),
        unknowns=tuple(items.unknowns),
        conflicts=conflicts,
        coverage=tuple(coverage),
        limit_reasons=tuple(sorted(items.limit_reasons)),
    )
