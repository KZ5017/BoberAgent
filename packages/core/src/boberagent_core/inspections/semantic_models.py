"""Strict Core-private C2 facts: source observations, never execution authority."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from boberagent_core.models import CoreModel

from .evidence_models import InspectionLimits, SourceCitation

PROFILE_ID = "m20-c2-deterministic"
PROFILE_VERSION = "1"


class SemanticInspectionLimits(InspectionLimits):
    max_semantic_files: int = Field(default=100, ge=1)
    max_semantic_bytes_total: int = Field(default=8 * 1024 * 1024, ge=1)
    max_semantic_bytes_per_file: int = Field(default=256 * 1024, ge=1)
    max_lines_per_file: int = Field(default=5000, ge=1)
    max_facts: int = Field(default=200, ge=1)
    max_entrypoint_candidates: int = Field(default=50, ge=1)
    max_parameter_candidates: int = Field(default=100, ge=1)
    max_dependency_observations: int = Field(default=100, ge=1)
    max_requirements: int = Field(default=100, ge=1)
    max_behavior_indicators: int = Field(default=200, ge=1)
    max_risk_indicators: int = Field(default=100, ge=1)
    max_unknowns: int = Field(default=100, ge=1)
    max_conflicts: int = Field(default=50, ge=1)
    max_ast_nodes: int = Field(default=20_000, ge=1)


class EpistemicState(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class SourceOrigin(StrEnum):
    CODE = "CODE"
    DECLARATIVE_METADATA = "DECLARATIVE_METADATA"
    DOCUMENTATION = "DOCUMENTATION"


class ParameterRole(StrEnum):
    TARGET_HOST = "TARGET_HOST"
    TARGET_URL = "TARGET_URL"
    TARGET_PORT = "TARGET_PORT"
    CALLBACK_HOST = "CALLBACK_HOST"
    CALLBACK_PORT = "CALLBACK_PORT"
    USERNAME = "USERNAME"
    CREDENTIAL = "CREDENTIAL"
    TIMEOUT = "TIMEOUT"
    MODE = "MODE"
    INPUT_FILE = "INPUT_FILE"
    UNKNOWN = "UNKNOWN"


class DependencyKind(StrEnum):
    DECLARED_PACKAGE = "DECLARED_PACKAGE"
    IMPORTED_MODULE = "IMPORTED_MODULE"
    INVOKED_SYSTEM_TOOL = "INVOKED_SYSTEM_TOOL"
    DOCUMENTED_DEPENDENCY = "DOCUMENTED_DEPENDENCY"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"


class ImportKind(StrEnum):
    STDLIB_LOOKING = "STDLIB_LOOKING"
    THIRD_PARTY_LOOKING = "THIRD_PARTY_LOOKING"
    LOCAL_RELATIVE = "LOCAL_RELATIVE"
    UNKNOWN = "UNKNOWN"


class RequirementKind(StrEnum):
    RUNTIME = "RUNTIME"
    PLATFORM = "PLATFORM"
    BUILD = "BUILD"
    CREDENTIAL = "CREDENTIAL"
    LISTENER = "LISTENER"
    PRIVILEGE = "PRIVILEGE"
    MANUAL_PARAMETER = "MANUAL_PARAMETER"
    ENVIRONMENT = "ENVIRONMENT"


class BehaviorKind(StrEnum):
    NETWORK_CONNECT = "NETWORK_CONNECT"
    NETWORK_BIND_LISTEN = "NETWORK_BIND_LISTEN"
    NETWORK_RESOLUTION = "NETWORK_RESOLUTION"
    SUBPROCESS_EXECUTION = "SUBPROCESS_EXECUTION"
    SHELL_EXECUTION = "SHELL_EXECUTION"
    FILE_WRITE = "FILE_WRITE"
    FILE_DELETE = "FILE_DELETE"
    ENVIRONMENT_ACCESS = "ENVIRONMENT_ACCESS"
    PRIVILEGE_CHECK = "PRIVILEGE_CHECK"
    DECLARED_SCRIPT = "DECLARED_SCRIPT"
    SERVICE_CONTROL = "SERVICE_CONTROL"
    REGISTRY_ACCESS = "REGISTRY_ACCESS"


class RiskKind(StrEnum):
    PRIVILEGED_EXECUTION = "PRIVILEGED_EXECUTION"
    DESTRUCTIVE_FILESYSTEM = "DESTRUCTIVE_FILESYSTEM"
    ARBITRARY_COMMAND_EXECUTION = "ARBITRARY_COMMAND_EXECUTION"
    SECURITY_CONTROL_MODIFICATION = "SECURITY_CONTROL_MODIFICATION"


class CoverageStatus(StrEnum):
    INSPECTED = "INSPECTED"
    PARTIAL = "PARTIAL"
    SKIPPED_UNSUPPORTED_TYPE = "SKIPPED_UNSUPPORTED_TYPE"
    SKIPPED_BINARY = "SKIPPED_BINARY"
    SKIPPED_ENCODING = "SKIPPED_ENCODING"
    SKIPPED_LIMIT = "SKIPPED_LIMIT"
    PARSER_FAILED = "PARSER_FAILED"


class SemanticItem(CoreModel):
    item_id: str = Field(pattern=r"^item-[0-9a-f]{64}$")
    source_path: str = Field(min_length=1, max_length=4096)
    epistemic_state: EpistemicState = EpistemicState.OBSERVED
    origin: SourceOrigin
    reason: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    citations: tuple[SourceCitation, ...] = ()
    supporting_fact_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def authority(self) -> Self:
        if self.epistemic_state is EpistemicState.OBSERVED and not self.citations:
            raise ValueError("OBSERVED source item requires evidence")
        if self.epistemic_state is EpistemicState.INFERRED and (
            not self.citations or not self.supporting_fact_refs
        ):
            raise ValueError("INFERRED item requires cited supporting facts")
        if any(citation.path != self.source_path for citation in self.citations):
            raise ValueError("item citation must reference its source path")
        return self


class SourceFact(SemanticItem):
    kind: Literal[
        "PYTHON_SOURCE",
        "SHEBANG",
        "MAIN_GUARD",
        "FUNCTION",
        "ASYNC_FUNCTION",
        "CLASS",
        "ARGPARSE",
        "ARGV",
        "DECLARATIVE_DATA",
        "DOCUMENTED_USAGE",
        "DOCUMENTED_TARGET",
        "DOCUMENTED_NO_CREDENTIALS",
    ]
    name: str | None = Field(default=None, max_length=128)


class EntrypointCandidate(SemanticItem):
    runtime: Literal["python", "shell", "powershell", "javascript"]
    invocation_style: Literal["SCRIPT_MAIN_GUARD", "SCRIPT_LEXICAL", "DECLARED_SCRIPT"]
    parameter_candidate_refs: tuple[str, ...] = ()


class ParameterCandidate(SemanticItem):
    name: str = Field(min_length=1, max_length=128)
    role: ParameterRole = ParameterRole.UNKNOWN
    required: bool | None = None
    default_literal: int | float | bool | None = None
    default_redacted: bool = False


class DependencyObservation(SemanticItem):
    kind: DependencyKind
    name: str = Field(min_length=1, max_length=256)
    import_kind: ImportKind | None = None
    version_constraint: str | None = Field(default=None, max_length=128)


class Requirement(SemanticItem):
    kind: RequirementKind
    name: str = Field(min_length=1, max_length=128)


class BehaviorIndicator(SemanticItem):
    kind: BehaviorKind


class RiskIndicator(SemanticItem):
    kind: RiskKind


class InspectionUnknown(SemanticItem):
    epistemic_state: Literal[EpistemicState.UNKNOWN] = EpistemicState.UNKNOWN


class InspectionConflict(CoreModel):
    conflict_id: str = Field(pattern=r"^conflict-[0-9a-f]{64}$")
    kind: Literal["RUNTIME_CLAIMS_DIFFER", "CREDENTIAL_CLAIMS_DIFFER"]
    item_refs: tuple[str, ...] = Field(min_length=2)
    citations: tuple[SourceCitation, ...] = Field(min_length=2)


class FileCoverage(CoreModel):
    path: str = Field(min_length=1, max_length=4096)
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: CoverageStatus
    reason: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    extractor_id: str
    extractor_version: Literal["1"] = "1"
    encoding: Literal["utf-8", "utf-8-bom", "utf-16-le-bom", "utf-16-be-bom"] | None = None


class SemanticInspectionDocument(CoreModel):
    document_version: Literal["m20-c2-deterministic-v1"] = "m20-c2-deterministic-v1"
    manifest_validated: Literal[True] = True
    zip_reconciled: Literal[True] = True
    verified_paths: tuple[str, ...]
    unverified_paths: tuple[str, ...]
    citations: tuple[SourceCitation, ...]
    facts: tuple[SourceFact, ...] = ()
    entrypoint_candidates: tuple[EntrypointCandidate, ...] = ()
    parameter_candidates: tuple[ParameterCandidate, ...] = ()
    dependency_observations: tuple[DependencyObservation, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    behavior_indicators: tuple[BehaviorIndicator, ...] = ()
    risk_indicators: tuple[RiskIndicator, ...] = ()
    unknowns: tuple[InspectionUnknown, ...] = ()
    conflicts: tuple[InspectionConflict, ...] = ()
    coverage: tuple[FileCoverage, ...]
    limit_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def references(self) -> Self:
        items = (
            *self.facts,
            *self.entrypoint_candidates,
            *self.parameter_candidates,
            *self.dependency_observations,
            *self.requirements,
            *self.behavior_indicators,
            *self.risk_indicators,
            *self.unknowns,
        )
        ids = {item.item_id for item in items}
        if len(ids) != len(items):
            raise ValueError("duplicate semantic item identity")
        fact_ids = {item.item_id for item in self.facts}
        parameter_ids = {item.item_id for item in self.parameter_candidates}
        coverage_paths = {item.path for item in self.coverage}
        if len(coverage_paths) != len(self.coverage):
            raise ValueError("duplicate coverage path")
        for item in items:
            if item.source_path not in coverage_paths:
                raise ValueError("source item has no coverage")
            if any(citation not in self.citations for citation in item.citations):
                raise ValueError("unregistered semantic citation")
            if not set(item.supporting_fact_refs) <= fact_ids:
                raise ValueError("unknown supporting fact")
        for entrypoint in self.entrypoint_candidates:
            if not set(entrypoint.parameter_candidate_refs) <= parameter_ids:
                raise ValueError("unknown parameter candidate")
        for conflict in self.conflicts:
            if not set(conflict.item_refs) <= ids or any(
                citation not in self.citations for citation in conflict.citations
            ):
                raise ValueError("unknown conflict evidence")
        return self
