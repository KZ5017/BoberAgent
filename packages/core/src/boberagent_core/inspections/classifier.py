"""Pure C3-v1 conditional classification of validated, persisted C2 evidence.

No source reader, parser, runtime, model, or authorization dependency belongs here.
Absence of a syntax indicator is not proof of safety; M20-D must separately bind
destinations/effects and validate policy before any future execution.
"""

from __future__ import annotations

from .classification_models import (
    ClassificationCoverage,
    ClassificationReason,
    ClassifierConfiguration,
    ReasonCode,
    ReasonDisposition,
    SupportClassification,
    SupportClassificationDocument,
    disposition,
    semantic_digest,
)
from .errors import InspectionError
from .identity import PoCInspectionRef
from .semantic_models import (
    BehaviorKind,
    CoverageStatus,
    DependencyKind,
    EpistemicState,
    ImportKind,
    ParameterRole,
    RequirementKind,
    RiskKind,
    SemanticInspectionDocument,
    SemanticItem,
    SourceOrigin,
)

# Closed relevance exceptions. Unknown extensions, vendor/generated source and
# executable helpers are material by default. A code item overrides an asset suffix.
_ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".md")
_NON_MATERIAL_GAPS = {
    "UNSUPPORTED_OR_GENERATED_TYPE",
    "BINARY_CONTENT",
    "INVALID_ENCODING",
    "UNSUPPORTED_NEWLINES",
    "NOT_SELECTED_BY_PROFILE_CONFIG",
}
_ASSISTANCE_UNKNOWN = {
    "MULTIPLE_ENTRYPOINT_CANDIDATES": ReasonCode.REQUIRES_ENTRYPOINT_SELECTION,
    "LEXICAL_ONLY_NO_COMPLETE_SEMANTICS": ReasonCode.REQUIRES_RUNTIME_CONFIRMATION,
    "AMBIGUOUS_PARAMETER_ROLE": ReasonCode.REQUIRES_MANUAL_PARAMETER,
}
_RISK_CODES = {
    RiskKind.PRIVILEGED_EXECUTION: ReasonCode.UNSUPPORTED_PRIVILEGED_EXECUTION,
    RiskKind.DESTRUCTIVE_FILESYSTEM: ReasonCode.UNSUPPORTED_DESTRUCTIVE_BEHAVIOR,
    RiskKind.ARBITRARY_COMMAND_EXECUTION: ReasonCode.UNSUPPORTED_ARBITRARY_COMMAND,
    RiskKind.SECURITY_CONTROL_MODIFICATION: ReasonCode.UNSUPPORTED_SECURITY_CONTROL_MODIFICATION,
}
_REQUIREMENT_CODES = {
    RequirementKind.CREDENTIAL: ReasonCode.REQUIRES_CREDENTIAL,
    RequirementKind.LISTENER: ReasonCode.REQUIRES_LISTENER,
    RequirementKind.MANUAL_PARAMETER: ReasonCode.REQUIRES_MANUAL_PARAMETER,
    RequirementKind.ENVIRONMENT: ReasonCode.REQUIRES_BROWSER_OR_ENVIRONMENT,
    RequirementKind.BUILD: ReasonCode.REQUIRES_BUILD_CONFIRMATION,
    RequirementKind.RUNTIME: ReasonCode.REQUIRES_RUNTIME_CONFIRMATION,
    RequirementKind.PLATFORM: ReasonCode.REQUIRES_RUNTIME_CONFIRMATION,
}


class _Reasons:
    def __init__(self) -> None:
        self.items: dict[ReasonCode, set[str]] = {}
        self.paths: dict[ReasonCode, set[str]] = {}
        self.conflicts: dict[ReasonCode, set[str]] = {}

    def add(
        self,
        code: ReasonCode,
        *,
        item: str | None = None,
        path: str | None = None,
        conflict: str | None = None,
    ) -> None:
        self.items.setdefault(code, set())
        self.paths.setdefault(code, set())
        self.conflicts.setdefault(code, set())
        if item is not None:
            self.items[code].add(item)
        if path is not None:
            self.paths[code].add(path)
        if conflict is not None:
            self.conflicts[code].add(conflict)

    def output(self) -> tuple[ClassificationReason, ...]:
        return tuple(
            ClassificationReason(
                code=code,
                item_refs=tuple(sorted(self.items[code])),
                conflict_refs=tuple(sorted(self.conflicts[code])),
                coverage_paths=tuple(sorted(self.paths[code])),
            )
            for code in sorted(self.items, key=lambda code: code.value)
        )


def semantic_items(document: SemanticInspectionDocument) -> tuple[SemanticItem, ...]:
    return (
        *document.facts,
        *document.entrypoint_candidates,
        *document.parameter_candidates,
        *document.dependency_observations,
        *document.requirements,
        *document.behavior_indicators,
        *document.risk_indicators,
        *document.unknowns,
    )


def validate_classification_evidence(
    result: SupportClassificationDocument, source: SemanticInspectionDocument
) -> None:
    """Resolve references against exact C2 output, without resolving source bytes."""
    items = {item.item_id for item in semantic_items(source)}
    unknowns = {item.item_id for item in source.unknowns}
    conflicts = {item.conflict_id for item in source.conflicts}
    paths = {entry.path for entry in source.coverage}
    if result.semantic_document_sha256 != semantic_digest(source):
        raise InspectionError("CLASSIFICATION_INPUT_CHANGED")
    for reason in result.reasons:
        if (
            not set(reason.item_refs) <= items
            or not set(reason.conflict_refs) <= conflicts
            or not set(reason.coverage_paths) <= paths
        ):
            raise InspectionError("CLASSIFICATION_EVIDENCE_INVALID")
    if (
        set(result.coverage.material_paths) | set(result.coverage.irrelevant_paths) != paths
        or not set(result.blocking_unknown_refs) <= unknowns
        or not set(result.assistance_unknown_refs) <= unknowns
        or not set(result.blocking_conflict_refs) <= conflicts
    ):
        raise InspectionError("CLASSIFICATION_EVIDENCE_INVALID")


def classify_support(
    semantic_inspection_ref: PoCInspectionRef,
    document: SemanticInspectionDocument,
    config: ClassifierConfiguration,
) -> SupportClassificationDocument:
    """Fixed Python-first v1 policy; classification has no execution authority."""
    # Revalidate even model_copy()/model_construct() inputs. The service additionally
    # validates the completed C2 envelope, bounds and byte-citation/source binding.
    document = SemanticInspectionDocument.model_validate_json(document.model_dump_json())
    items = semantic_items(document)
    if (
        len(items) + len(document.conflicts) > config.max_input_items
        or len(document.coverage) > config.max_coverage_paths
    ):
        raise InspectionError("CLASSIFICATION_INPUT_LIMIT")

    reasons = _Reasons()
    by_path: dict[str, list[SemanticItem]] = {}
    for item in items:
        by_path.setdefault(item.source_path, []).append(item)
    coverage = {entry.path: entry for entry in document.coverage}
    material: set[str] = set()
    irrelevant: set[str] = set()
    for entry in document.coverage:
        name = entry.path.rsplit("/", 1)[-1].lower()
        code_evidence = any(
            item.origin is not SourceOrigin.DOCUMENTATION
            and item.epistemic_state is not EpistemicState.UNKNOWN
            for item in by_path.get(entry.path, ())
        )
        directory = entry.size_bytes is None and entry.sha256 is None
        asset = name.endswith(_ASSET_SUFFIXES) or name.startswith("readme")
        # requirements.txt remains material even without a recognized dependency.
        if directory or (asset and not code_evidence and name != "requirements.txt"):
            irrelevant.add(entry.path)
        else:
            material.add(entry.path)

    unknown_blockers: set[str] = set()
    unknown_assistance: set[str] = set()
    unknown_codes: dict[str, ReasonCode] = {}
    for unknown in document.unknowns:
        if unknown.reason == "EXTRACTOR_LIMITATIONS":
            continue
        code = _ASSISTANCE_UNKNOWN.get(unknown.reason)
        # A Python helper lacking its own main guard is not a second entrypoint.
        helper_only = unknown.reason == "ENTRYPOINT_UNRESOLVED" and any(
            entry.source_path != unknown.source_path for entry in document.entrypoint_candidates
        )
        unknown_parameters = [
            parameter
            for parameter in document.parameter_candidates
            if parameter.source_path == unknown.source_path
            and parameter.role is ParameterRole.UNKNOWN
        ]
        optional_cosmetic = (
            unknown.reason == "AMBIGUOUS_PARAMETER_ROLE"
            and bool(unknown_parameters)
            and all(parameter.required is False for parameter in unknown_parameters)
        )
        if (
            (unknown.source_path in irrelevant and unknown.reason in _NON_MATERIAL_GAPS)
            or helper_only
            or optional_cosmetic
        ):
            code = ReasonCode.NON_BLOCKING_UNKNOWN
        elif unknown.origin is SourceOrigin.DOCUMENTATION:
            code = ReasonCode.REQUIRES_DOCUMENTED_RISK_REVIEW
        elif code is None:
            code = ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN
        unknown_codes[unknown.item_id] = code
    for unknown in document.unknowns:
        if unknown.reason == "EXTRACTOR_LIMITATIONS":
            causes = {
                unknown_codes[item.item_id]
                for item in document.unknowns
                if item.source_path == unknown.source_path and item.item_id in unknown_codes
            }
            code = (
                ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN
                if not causes
                or any(disposition(value) is ReasonDisposition.BLOCKER for value in causes)
                else sorted(
                    causes,
                    key=lambda value: (
                        disposition(value) is not ReasonDisposition.ASSISTANCE,
                        value.value,
                    ),
                )[0]
            )
            unknown_codes[unknown.item_id] = code
        code = unknown_codes[unknown.item_id]
        reasons.add(code, item=unknown.item_id)
        if disposition(code) is ReasonDisposition.BLOCKER:
            unknown_blockers.add(unknown.item_id)
        elif disposition(code) is ReasonDisposition.ASSISTANCE:
            unknown_assistance.add(unknown.item_id)

    incomplete: set[str] = set()
    for path in sorted(material):
        entry = coverage[path]
        if entry.status is CoverageStatus.INSPECTED:
            if path not in document.verified_paths or entry.sha256 is None:
                raise InspectionError("CLASSIFICATION_EVIDENCE_INVALID")
            continue
        incomplete.add(path)
        gaps = [item for item in document.unknowns if item.source_path == path]
        explained_partial = (
            entry.status is CoverageStatus.PARTIAL
            and bool(gaps)
            and not any(item.item_id in unknown_blockers for item in gaps)
            and not entry.reason.endswith("LIMIT")
        )
        if not explained_partial:
            reasons.add(ReasonCode.UNSUPPORTED_INSUFFICIENT_COVERAGE, path=path)
    # Truncation can hide requirements/risks even if no unknown survived its bound.
    if document.limit_reasons:
        reasons.add(ReasonCode.UNSUPPORTED_INSUFFICIENT_COVERAGE)

    for risk in document.risk_indicators:
        code = _RISK_CODES[risk.kind]
        if risk.origin is SourceOrigin.DOCUMENTATION:
            code = ReasonCode.REQUIRES_DOCUMENTED_RISK_REVIEW
        elif risk.epistemic_state is not EpistemicState.OBSERVED:
            code = ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN
        reasons.add(code, item=risk.item_id)
    for requirement in document.requirements:
        if requirement.kind is RequirementKind.PRIVILEGE:
            code = (
                ReasonCode.UNSUPPORTED_PRIVILEGED_EXECUTION
                if requirement.origin is not SourceOrigin.DOCUMENTATION
                and requirement.epistemic_state is EpistemicState.OBSERVED
                else ReasonCode.REQUIRES_DOCUMENTED_RISK_REVIEW
            )
        else:
            code = _REQUIREMENT_CODES[requirement.kind]
        reasons.add(code, item=requirement.item_id)

    # Privilege-check syntax is not a privilege requirement. Generic process/file
    # syntax is not proof of persistence/destruction either, but C2 cannot prove its
    # boundaries, so it blocks AUTOMATIC rather than inventing severe observed facts.
    for behavior in document.behavior_indicators:
        if behavior.kind is BehaviorKind.NETWORK_BIND_LISTEN:
            reasons.add(ReasonCode.REQUIRES_LISTENER, item=behavior.item_id)
        elif behavior.kind is BehaviorKind.ENVIRONMENT_ACCESS:
            reasons.add(ReasonCode.REQUIRES_BROWSER_OR_ENVIRONMENT, item=behavior.item_id)
        elif behavior.kind in {
            BehaviorKind.SUBPROCESS_EXECUTION,
            BehaviorKind.SHELL_EXECUTION,
            BehaviorKind.FILE_WRITE,
            BehaviorKind.FILE_DELETE,
            BehaviorKind.SERVICE_CONTROL,
            BehaviorKind.REGISTRY_ACCESS,
        }:
            reasons.add(ReasonCode.UNSUPPORTED_UNBOUNDED_EFFECT, item=behavior.item_id)

    for dependency in document.dependency_observations:
        if dependency.kind is DependencyKind.IMPORTED_MODULE:
            if dependency.import_kind is ImportKind.STDLIB_LOOKING:
                continue
            if dependency.import_kind in {None, ImportKind.UNKNOWN}:
                reasons.add(ReasonCode.UNSUPPORTED_DEPENDENCY_UNKNOWN, item=dependency.item_id)
                continue
        elif dependency.kind is DependencyKind.UNKNOWN_DEPENDENCY:
            reasons.add(ReasonCode.UNSUPPORTED_DEPENDENCY_UNKNOWN, item=dependency.item_id)
            continue
        reasons.add(ReasonCode.REQUIRES_DEPENDENCY_REVIEW, item=dependency.item_id)

    credible = [
        candidate
        for candidate in document.entrypoint_candidates
        if candidate.origin is not SourceOrigin.DOCUMENTATION
        and candidate.epistemic_state is EpistemicState.OBSERVED
    ]
    if not credible:
        reasons.add(ReasonCode.UNSUPPORTED_ENTRYPOINT_UNKNOWN)
        executable_paths = [
            path for path in material if path.lower().endswith((".exe", ".dll", ".so", ".bin"))
        ]
        if executable_paths:
            for path in executable_paths:
                reasons.add(ReasonCode.UNSUPPORTED_BINARY_ONLY, path=path)
    elif len(credible) > 1:
        for candidate in credible:
            reasons.add(ReasonCode.REQUIRES_ENTRYPOINT_SELECTION, item=candidate.item_id)
    else:
        reasons.add(ReasonCode.SUPPORTED_ENTRYPOINT_UNAMBIGUOUS, item=credible[0].item_id)

    parameters = {item.item_id: item for item in document.parameter_candidates}
    for candidate in credible:
        if candidate.runtime == "shell":
            reasons.add(ReasonCode.REQUIRES_RUNTIME_CONFIRMATION, item=candidate.item_id)
        elif candidate.runtime != "python":
            reasons.add(ReasonCode.UNSUPPORTED_RUNTIME, item=candidate.item_id)
        if candidate.source_path not in material:
            raise InspectionError("CLASSIFICATION_EVIDENCE_INVALID")
        target_parameters = [
            parameters[ref]
            for ref in candidate.parameter_candidate_refs
            if parameters[ref].role in {ParameterRole.TARGET_HOST, ParameterRole.TARGET_URL}
        ]
        if candidate.runtime == "python":
            source_facts = [
                fact
                for fact in document.facts
                if (
                    fact.source_path == candidate.source_path
                    and fact.origin is SourceOrigin.CODE
                    and fact.epistemic_state is EpistemicState.OBSERVED
                )
            ]
            if not any(fact.kind == "PYTHON_SOURCE" for fact in source_facts) or (
                candidate.invocation_style == "SCRIPT_MAIN_GUARD"
                and not any(fact.kind == "MAIN_GUARD" for fact in source_facts)
            ):
                reasons.add(ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN, item=candidate.item_id)
            if len(target_parameters) != 1 or any(
                parameter.origin is not SourceOrigin.CODE
                or parameter.epistemic_state is not EpistemicState.OBSERVED
                or parameter.source_path != candidate.source_path
                for parameter in target_parameters
            ):
                reasons.add(ReasonCode.UNSUPPORTED_TARGET_BOUNDARY, item=candidate.item_id)
            elif target_parameters[0].required is not True:
                reasons.add(ReasonCode.REQUIRES_MANUAL_PARAMETER, item=target_parameters[0].item_id)
            else:
                reasons.add(ReasonCode.SUPPORTED_PYTHON_SINGLE_TARGET, item=candidate.item_id)
                reasons.add(
                    ReasonCode.SUPPORTED_PYTHON_SINGLE_TARGET, item=target_parameters[0].item_id
                )

    for parameter in document.parameter_candidates:
        if parameter.role in {ParameterRole.CREDENTIAL, ParameterRole.USERNAME}:
            code = ReasonCode.REQUIRES_CREDENTIAL
        elif parameter.role in {ParameterRole.CALLBACK_HOST, ParameterRole.CALLBACK_PORT}:
            code = ReasonCode.REQUIRES_LISTENER
        elif parameter.role in {ParameterRole.INPUT_FILE, ParameterRole.MODE} or (
            parameter.role is ParameterRole.UNKNOWN and parameter.required is not False
        ):
            code = ReasonCode.REQUIRES_MANUAL_PARAMETER
        else:
            continue
        reasons.add(code, item=parameter.item_id)

    for conflict in document.conflicts:
        reasons.add(ReasonCode.UNSUPPORTED_MATERIAL_CONFLICT, conflict=conflict.conflict_id)
        for item_ref in conflict.item_refs:
            reasons.add(ReasonCode.UNSUPPORTED_MATERIAL_CONFLICT, item=item_ref)

    if ReasonCode.UNSUPPORTED_INSUFFICIENT_COVERAGE not in reasons.items:
        for path in sorted(material):
            reasons.add(ReasonCode.SUPPORTED_PROFILE_COVERAGE, path=path)
    output = reasons.output()
    dispositions = {disposition(reason.code) for reason in output}
    classification = (
        SupportClassification.UNSUPPORTED
        if ReasonDisposition.BLOCKER in dispositions
        else SupportClassification.ASSISTED
        if ReasonDisposition.ASSISTANCE in dispositions
        else SupportClassification.AUTOMATIC
    )
    result = SupportClassificationDocument(
        semantic_inspection_ref=semantic_inspection_ref,
        semantic_document_sha256=semantic_digest(document),
        classification=classification,
        reasons=output,
        coverage=ClassificationCoverage(
            material_paths=tuple(sorted(material)),
            incomplete_material_paths=tuple(sorted(incomplete)),
            irrelevant_paths=tuple(sorted(irrelevant)),
        ),
        blocking_unknown_refs=tuple(sorted(unknown_blockers)),
        assistance_unknown_refs=tuple(sorted(unknown_assistance)),
        blocking_conflict_refs=tuple(sorted(item.conflict_id for item in document.conflicts)),
    )
    validate_classification_evidence(result, document)
    return result
