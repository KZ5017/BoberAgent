"""Versioned conditional support, not execution authority or runtime readiness."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self

from boberagent_contracts import JsonValue
from pydantic import Field, StrictInt, TypeAdapter, model_validator

from boberagent_core.models import CoreModel

from .evidence_models import InspectionLimits
from .identity import PoCInspectionRef
from .semantic_models import SemanticInspectionDocument

CLASSIFIER_PROFILE_ID: Literal["m20-c3-support-classifier"] = "m20-c3-support-classifier"
CLASSIFIER_PROFILE_VERSION: Literal["2"] = "2"


class SupportClassification(StrEnum):
    AUTOMATIC = "AUTOMATIC"
    ASSISTED = "ASSISTED"
    UNSUPPORTED = "UNSUPPORTED"


class ReasonCode(StrEnum):
    SUPPORTED_PYTHON_SINGLE_TARGET = "SUPPORTED_PYTHON_SINGLE_TARGET"
    SUPPORTED_ENTRYPOINT_UNAMBIGUOUS = "SUPPORTED_ENTRYPOINT_UNAMBIGUOUS"
    SUPPORTED_PROFILE_COVERAGE = "SUPPORTED_PROFILE_COVERAGE"
    NON_BLOCKING_UNKNOWN = "NON_BLOCKING_UNKNOWN"
    REQUIRES_CREDENTIAL = "REQUIRES_CREDENTIAL"
    REQUIRES_LISTENER = "REQUIRES_LISTENER"
    REQUIRES_BROWSER_OR_ENVIRONMENT = "REQUIRES_BROWSER_OR_ENVIRONMENT"
    REQUIRES_MANUAL_PARAMETER = "REQUIRES_MANUAL_PARAMETER"
    REQUIRES_ENTRYPOINT_SELECTION = "REQUIRES_ENTRYPOINT_SELECTION"
    REQUIRES_BUILD_CONFIRMATION = "REQUIRES_BUILD_CONFIRMATION"
    REQUIRES_RUNTIME_CONFIRMATION = "REQUIRES_RUNTIME_CONFIRMATION"
    REQUIRES_DEPENDENCY_REVIEW = "REQUIRES_DEPENDENCY_REVIEW"
    REQUIRES_DOCUMENTED_RISK_REVIEW = "REQUIRES_DOCUMENTED_RISK_REVIEW"
    UNSUPPORTED_RUNTIME = "UNSUPPORTED_RUNTIME"
    UNSUPPORTED_PRIVILEGED_EXECUTION = "UNSUPPORTED_PRIVILEGED_EXECUTION"
    UNSUPPORTED_SECURITY_CONTROL_MODIFICATION = "UNSUPPORTED_SECURITY_CONTROL_MODIFICATION"
    UNSUPPORTED_DESTRUCTIVE_BEHAVIOR = "UNSUPPORTED_DESTRUCTIVE_BEHAVIOR"
    UNSUPPORTED_ARBITRARY_COMMAND = "UNSUPPORTED_ARBITRARY_COMMAND"
    UNSUPPORTED_BINARY_ONLY = "UNSUPPORTED_BINARY_ONLY"
    UNSUPPORTED_INSUFFICIENT_COVERAGE = "UNSUPPORTED_INSUFFICIENT_COVERAGE"
    UNSUPPORTED_ENTRYPOINT_UNKNOWN = "UNSUPPORTED_ENTRYPOINT_UNKNOWN"
    UNSUPPORTED_TARGET_BOUNDARY = "UNSUPPORTED_TARGET_BOUNDARY"
    UNSUPPORTED_MATERIAL_CONFLICT = "UNSUPPORTED_MATERIAL_CONFLICT"
    UNSUPPORTED_MATERIAL_UNKNOWN = "UNSUPPORTED_MATERIAL_UNKNOWN"
    UNSUPPORTED_UNBOUNDED_EFFECT = "UNSUPPORTED_UNBOUNDED_EFFECT"
    REQUIRES_FILESYSTEM_REVIEW = "REQUIRES_FILESYSTEM_REVIEW"
    UNSUPPORTED_DEPENDENCY_UNKNOWN = "UNSUPPORTED_DEPENDENCY_UNKNOWN"


class ReasonDisposition(StrEnum):
    QUALIFIER = "QUALIFIER"
    INFORMATION = "INFORMATION"
    ASSISTANCE = "ASSISTANCE"
    BLOCKER = "BLOCKER"


def disposition(code: ReasonCode) -> ReasonDisposition:
    """The bounded rule code also identifies its fixed profile rule."""
    if code.value.startswith("UNSUPPORTED_"):
        return ReasonDisposition.BLOCKER
    if code.value.startswith("REQUIRES_"):
        return ReasonDisposition.ASSISTANCE
    if code is ReasonCode.NON_BLOCKING_UNKNOWN:
        return ReasonDisposition.INFORMATION
    return ReasonDisposition.QUALIFIER


class ClassifierConfiguration(CoreModel):
    """Resource bounds only; no configuration switch can relax v1 support policy."""

    max_input_items: StrictInt = Field(default=4000, ge=1, le=100_000)
    max_coverage_paths: StrictInt = Field(default=10_000, ge=1, le=100_000)


class ClassificationInspectionLimits(InspectionLimits):
    """Typed C3 request configuration in the existing attempt configuration JSON.

    Inherited evidence limits are retained for compatibility, not used to read source.
    The semantic identity and effective classifier bounds participate in the reuse key.
    """

    semantic_inspection_ref: PoCInspectionRef
    semantic_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classifier_config: ClassifierConfiguration = Field(default_factory=ClassifierConfiguration)


class ClassificationReason(CoreModel):
    code: ReasonCode
    item_refs: tuple[str, ...] = ()
    conflict_refs: tuple[str, ...] = ()
    coverage_paths: tuple[str, ...] = ()

    @model_validator(mode="after")
    def stable_refs(self) -> Self:
        for values in (self.item_refs, self.conflict_refs, self.coverage_paths):
            if values != tuple(sorted(set(values))):
                raise ValueError("classification evidence references must be unique and sorted")
        return self


class ClassificationCoverage(CoreModel):
    """References C2 coverage rows by unique path; no raw content or excerpts."""

    material_paths: tuple[str, ...]
    incomplete_material_paths: tuple[str, ...]
    irrelevant_paths: tuple[str, ...]

    @model_validator(mode="after")
    def shape(self) -> Self:
        for values in (self.material_paths, self.incomplete_material_paths, self.irrelevant_paths):
            if values != tuple(sorted(set(values))):
                raise ValueError("coverage paths must be unique and sorted")
        if set(self.material_paths) & set(self.irrelevant_paths) or not set(
            self.incomplete_material_paths
        ) <= set(self.material_paths):
            raise ValueError("inconsistent classification coverage")
        return self


class SupportClassificationDocument(CoreModel):
    document_version: Literal["m20-c3-support-classifier-v1", "m20-c3-support-classifier-v2"] = (
        "m20-c3-support-classifier-v2"
    )
    classifier_profile: Literal["m20-c3-support-classifier"] = CLASSIFIER_PROFILE_ID
    classifier_version: Literal["1", "2"] = CLASSIFIER_PROFILE_VERSION
    semantic_inspection_ref: PoCInspectionRef
    semantic_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: SupportClassification
    reasons: tuple[ClassificationReason, ...] = Field(min_length=1)
    coverage: ClassificationCoverage
    blocking_unknown_refs: tuple[str, ...] = ()
    assistance_unknown_refs: tuple[str, ...] = ()
    blocking_conflict_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def precedence(self) -> Self:
        if self.document_version != f"m20-c3-support-classifier-v{self.classifier_version}":
            raise ValueError("classification document/version mismatch")
        codes = tuple(reason.code.value for reason in self.reasons)
        if codes != tuple(sorted(set(codes))):
            raise ValueError("classification reasons must be unique and sorted")
        for refs in (
            self.blocking_unknown_refs,
            self.assistance_unknown_refs,
            self.blocking_conflict_refs,
        ):
            if refs != tuple(sorted(set(refs))):
                raise ValueError("blocker references must be unique and sorted")
        blocker_items = {
            ref
            for reason in self.reasons
            if disposition(reason.code) is ReasonDisposition.BLOCKER
            for ref in reason.item_refs
        }
        assistance_items = {
            ref
            for reason in self.reasons
            if disposition(reason.code) is ReasonDisposition.ASSISTANCE
            for ref in reason.item_refs
        }
        blocker_conflicts = {
            ref
            for reason in self.reasons
            if disposition(reason.code) is ReasonDisposition.BLOCKER
            for ref in reason.conflict_refs
        }
        if (
            not set(self.blocking_unknown_refs) <= blocker_items
            or not set(self.assistance_unknown_refs) <= assistance_items
            or not set(self.blocking_conflict_refs) <= blocker_conflicts
            or set(self.blocking_unknown_refs) & set(self.assistance_unknown_refs)
        ):
            raise ValueError("unknown/conflict blockers require corresponding reason evidence")
        dispositions = {disposition(reason.code) for reason in self.reasons}
        expected = (
            SupportClassification.UNSUPPORTED
            if ReasonDisposition.BLOCKER in dispositions
            else SupportClassification.ASSISTED
            if ReasonDisposition.ASSISTANCE in dispositions
            else SupportClassification.AUTOMATIC
        )
        if expected is not self.classification:
            raise ValueError("classification disagrees with reason precedence")
        if self.classification is SupportClassification.AUTOMATIC and not {
            ReasonCode.SUPPORTED_PYTHON_SINGLE_TARGET,
            ReasonCode.SUPPORTED_ENTRYPOINT_UNAMBIGUOUS,
            ReasonCode.SUPPORTED_PROFILE_COVERAGE,
        } <= {reason.code for reason in self.reasons}:
            raise ValueError("AUTOMATIC requires all positive profile gates")
        return self


def _canonical(value: JsonValue) -> JsonValue:
    """C2 collections are evidence sets, not ordered instructions/argv."""
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted(
            (_canonical(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    return value


def semantic_digest(document: SemanticInspectionDocument) -> str:
    normalized = _canonical(TypeAdapter(JsonValue).validate_json(document.model_dump_json()))
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
