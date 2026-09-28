"""Bounded evidence emission shared by deterministic, non-executing extractors."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import TypedDict

from .evidence import VerifiedSource
from .models import SourceCitation
from .semantic_models import (
    BehaviorIndicator,
    BehaviorKind,
    DependencyObservation,
    EntrypointCandidate,
    EpistemicState,
    FileEffectScope,
    InspectionUnknown,
    ParameterCandidate,
    ParameterRole,
    Requirement,
    RiskIndicator,
    RiskKind,
    SemanticInspectionLimits,
    SemanticItem,
    SourceFact,
    SourceOrigin,
)
from .text import DecodedSource


class SemanticLimit(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ParserCoverageError(ValueError):
    """Expected syntax/format rejection, not an internal inspector defect."""


class ItemEvidence(TypedDict):
    item_id: str
    source_path: str
    origin: SourceOrigin
    reason: str
    citations: tuple[SourceCitation, ...]


def stable_id(prefix: str, value: object) -> str:
    return (
        prefix
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def safe_name(value: str) -> bool:
    return len(value) <= 128 and bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", value))


def parameter_role(name: str) -> ParameterRole:
    key = name.lstrip("-$").lower().replace("-", "_")
    return {
        "target": ParameterRole.TARGET_HOST,
        "host": ParameterRole.TARGET_HOST,
        "target_host": ParameterRole.TARGET_HOST,
        "url": ParameterRole.TARGET_URL,
        "target_url": ParameterRole.TARGET_URL,
        "port": ParameterRole.TARGET_PORT,
        "target_port": ParameterRole.TARGET_PORT,
        "lhost": ParameterRole.CALLBACK_HOST,
        "callback_host": ParameterRole.CALLBACK_HOST,
        "lport": ParameterRole.CALLBACK_PORT,
        "callback_port": ParameterRole.CALLBACK_PORT,
        "username": ParameterRole.USERNAME,
        "user": ParameterRole.USERNAME,
        "password": ParameterRole.CREDENTIAL,
        "token": ParameterRole.CREDENTIAL,
        "credential": ParameterRole.CREDENTIAL,
        "timeout": ParameterRole.TIMEOUT,
        "mode": ParameterRole.MODE,
        "file": ParameterRole.INPUT_FILE,
        "path": ParameterRole.INPUT_FILE,
    }.get(key, ParameterRole.UNKNOWN)


class ExtractedItems:
    def __init__(self, source: VerifiedSource, limits: SemanticInspectionLimits) -> None:
        self.source = source
        self.limits = limits
        self.facts: list[SourceFact] = []
        self.entrypoints: list[EntrypointCandidate] = []
        self.parameters: list[ParameterCandidate] = []
        self.dependencies: list[DependencyObservation] = []
        self.requirements: list[Requirement] = []
        self.behaviors: list[BehaviorIndicator] = []
        self.risks: list[RiskIndicator] = []
        self.unknowns: list[InspectionUnknown] = []
        self.citations: list[SourceCitation] = []
        self.limit_reasons: set[str] = set()
        self.gap_paths: set[str] = set()

    def check_time(self) -> None:
        if time.monotonic() > self.source.deadline:
            raise SemanticLimit("WALL_TIME_LIMIT")

    def add(self, item: SemanticItem) -> None:
        self.check_time()
        if isinstance(item, InspectionUnknown):
            self.gap_paths.add(item.source_path)
        collections = (
            (SourceFact, self.facts, self.limits.max_facts, "FACT_LIMIT"),
            (
                EntrypointCandidate,
                self.entrypoints,
                self.limits.max_entrypoint_candidates,
                "ENTRYPOINT_LIMIT",
            ),
            (
                ParameterCandidate,
                self.parameters,
                self.limits.max_parameter_candidates,
                "PARAMETER_LIMIT",
            ),
            (
                DependencyObservation,
                self.dependencies,
                self.limits.max_dependency_observations,
                "DEPENDENCY_LIMIT",
            ),
            (Requirement, self.requirements, self.limits.max_requirements, "REQUIREMENT_LIMIT"),
            (
                BehaviorIndicator,
                self.behaviors,
                self.limits.max_behavior_indicators,
                "BEHAVIOR_LIMIT",
            ),
            (RiskIndicator, self.risks, self.limits.max_risk_indicators, "RISK_LIMIT"),
            (InspectionUnknown, self.unknowns, self.limits.max_unknowns, "UNKNOWN_LIMIT"),
        )
        for cls, collection, bound, code in collections:
            if isinstance(item, cls):
                if any(old.item_id == item.item_id for old in collection):
                    return
                if len(collection) >= bound:
                    raise SemanticLimit(code)
                missing = [
                    citation for citation in item.citations if citation not in self.citations
                ]
                if len(self.citations) + len(missing) > self.limits.max_citations:
                    raise SemanticLimit("CITATION_LIMIT")
                # Dispatch explicitly to keep heterogeneous collection typing sound.
                self._append(item)
                self.citations.extend(missing)
                return
        raise TypeError("unsupported semantic item")

    def _append(self, item: SemanticItem) -> None:
        if isinstance(item, SourceFact):
            self.facts.append(item)
        elif isinstance(item, EntrypointCandidate):
            self.entrypoints.append(item)
        elif isinstance(item, ParameterCandidate):
            self.parameters.append(item)
        elif isinstance(item, DependencyObservation):
            self.dependencies.append(item)
        elif isinstance(item, Requirement):
            self.requirements.append(item)
        elif isinstance(item, BehaviorIndicator):
            self.behaviors.append(item)
        elif isinstance(item, RiskIndicator):
            self.risks.append(item)
        elif isinstance(item, InspectionUnknown):
            self.unknowns.append(item)

    def gap(self, path: str, origin: SourceOrigin, reason: str) -> None:
        """Coverage itself remains explicit even if the unknown collection is full."""
        self.gap_paths.add(path)
        item = InspectionUnknown(
            item_id=stable_id("item-", [path, reason, "unknown"]),
            source_path=path,
            origin=origin,
            reason=reason,
        )
        if len(self.unknowns) < self.limits.max_unknowns:
            if item not in self.unknowns:
                self.unknowns.append(item)
        else:
            self.limit_reasons.add("UNKNOWN_LIMIT")


class FileExtractor:
    def __init__(
        self,
        items: ExtractedItems,
        path: str,
        content: bytes,
        decoded: DecodedSource,
        origin: SourceOrigin,
        extractor_id: str,
    ) -> None:
        self.items, self.path, self.content = items, path, content
        self.decoded, self.origin, self.extractor_id = decoded, origin, extractor_id

    def evidence(self, start: int, end: int, reason: str, key: str = "") -> ItemEvidence:
        self.items.check_time()
        byte_start, byte_end = self.decoded.byte_span(start, end)
        if byte_end - byte_start > self.items.limits.max_citation_bytes:
            raise SemanticLimit("CITATION_BYTES_LIMIT")
        inspection = self.items.source.inspection
        entry = self.items.source.entries[self.path]
        assert entry.sha256 is not None
        citation = SourceCitation(
            raw_artifact_ref=inspection.raw_artifact_ref,
            raw_sha256=inspection.raw_sha256,
            manifest_artifact_ref=inspection.manifest_artifact_ref,
            manifest_sha256=inspection.manifest_sha256,
            path=self.path,
            entry_sha256=entry.sha256,
            start=byte_start,
            end=byte_end,
            reader_id=self.extractor_id,
            reader_version="2",
        )
        self.items.source.validate_citation(citation, self.content)
        return ItemEvidence(
            item_id=stable_id(
                "item-", [self.path, byte_start, byte_end, self.extractor_id, reason, key]
            ),
            source_path=self.path,
            origin=self.origin,
            reason=reason,
            citations=(citation,),
        )

    def parameter(self, start: int, end: int, name: str, required: bool | None = None) -> None:
        role = parameter_role(name)
        self.items.add(
            ParameterCandidate(
                **self.evidence(start, end, "LITERAL_PARAMETER", name),
                name=name,
                role=role,
                required=required,
            )
        )
        if role is ParameterRole.UNKNOWN:
            self.items.gap(self.path, self.origin, "AMBIGUOUS_PARAMETER_ROLE")

    def indicator(self, start: int, end: int, kind: object) -> None:
        if isinstance(kind, BehaviorKind):
            self.items.add(
                BehaviorIndicator(
                    **self.evidence(start, end, "SOURCE_SYNTAX_INDICATOR", kind.value),
                    kind=kind,
                )
            )
        elif isinstance(kind, RiskKind):
            self.items.add(
                RiskIndicator(
                    **self.evidence(start, end, "SOURCE_SYNTAX_RISK", kind.value),
                    kind=kind,
                )
            )

    def filesystem_effect(
        self, start: int, end: int, kind: BehaviorKind, scope: FileEffectScope
    ) -> None:
        """Keep the primitive separate from the evidence-backed scope assessment."""
        self.items.add(
            BehaviorIndicator(
                **self.evidence(start, end, f"FILE_EFFECT_SCOPE_{scope.value}", kind.value),
                kind=kind,
            )
        )
        if scope is FileEffectScope.UNKNOWN:
            self.unknown(start, end, "FILE_EFFECT_SCOPE_UNKNOWN")
        elif scope is FileEffectScope.BROAD and kind is BehaviorKind.FILE_DELETE:
            self.items.add(
                RiskIndicator(
                    **self.evidence(start, end, "BROAD_LITERAL_RECURSIVE_DELETE"),
                    kind=RiskKind.DESTRUCTIVE_FILESYSTEM,
                )
            )

    def unknown(self, start: int, end: int, reason: str) -> None:
        self.items.add(
            InspectionUnknown(
                **self.evidence(start, end, reason),
                epistemic_state=EpistemicState.UNKNOWN,
            )
        )
