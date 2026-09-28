"""Typed C2 inputs exercise rules absent from current extractors without new detectors.

These fixtures test the classifier boundary, not claims that C2 detects every
persistence/mass-target/build/browser condition. Unknowns remain unknown evidence.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.inspections import (
    ClassifierConfiguration,
    InspectionError,
    ReasonCode,
    SupportClassification,
    SupportClassificationDocument,
)
from boberagent_core.inspections.classification_models import ClassificationReason, semantic_digest
from boberagent_core.inspections.classifier import (
    classify_support,
    validate_classification_evidence,
)
from boberagent_core.inspections.identity import PoCInspectionRef
from boberagent_core.inspections.semantic_models import (
    CoverageStatus,
    EpistemicState,
    InspectionUnknown,
    Requirement,
    RequirementKind,
    RiskIndicator,
    RiskKind,
    SemanticInspectionDocument,
    SourceOrigin,
)
from pydantic import ValidationError
from test_poc_inspection_c2 import completed_document, prepare
from test_poc_inspection_c3 import CHECKER, codes

REF = PoCInspectionRef("inspection-classifier-unit")


@pytest.fixture
def semantic(database: CoreDatabase, tmp_path: Path) -> SemanticInspectionDocument:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    return completed_document(service, requested)[1]


def identity(name: str) -> str:
    return "item-" + hashlib.sha256(name.encode()).hexdigest()


def result(document: SemanticInspectionDocument) -> SupportClassificationDocument:
    return classify_support(REF, document, ClassifierConfiguration())


@pytest.mark.parametrize("kind", list(RiskKind))
def test_hard_risk_precedes_assistance(
    semantic: SemanticInspectionDocument, kind: RiskKind
) -> None:
    evidence = semantic.facts[0].citations
    risk = RiskIndicator(
        item_id=identity(kind),
        source_path="checker.py",
        origin=SourceOrigin.CODE,
        reason="CITED_RISK",
        citations=evidence,
        kind=kind,
    )
    requirement = Requirement(
        item_id=identity("credential"),
        source_path="checker.py",
        origin=SourceOrigin.CODE,
        reason="CREDENTIAL_PARAMETER",
        citations=evidence,
        kind=RequirementKind.CREDENTIAL,
        name="credential",
    )
    document = semantic.model_copy(
        update={"risk_indicators": (risk,), "requirements": (requirement,)}
    )
    classified = result(document)
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert ReasonCode.REQUIRES_CREDENTIAL in codes(classified)
    decisive = [reason for reason in classified.reasons if risk.item_id in reason.item_refs]
    assert len(decisive) == 1 and decisive[0].code.value.startswith("UNSUPPORTED_")
    validate_classification_evidence(classified, document)


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        (RequirementKind.BUILD, ReasonCode.REQUIRES_BUILD_CONFIRMATION),
        (RequirementKind.RUNTIME, ReasonCode.REQUIRES_RUNTIME_CONFIRMATION),
        (RequirementKind.ENVIRONMENT, ReasonCode.REQUIRES_BROWSER_OR_ENVIRONMENT),
        (RequirementKind.LISTENER, ReasonCode.REQUIRES_LISTENER),
        (RequirementKind.PRIVILEGE, ReasonCode.UNSUPPORTED_PRIVILEGED_EXECUTION),
    ],
)
def test_typed_prerequisite_rules(
    semantic: SemanticInspectionDocument, kind: RequirementKind, reason: ReasonCode
) -> None:
    requirement = Requirement(
        item_id=identity(kind),
        source_path="checker.py",
        origin=SourceOrigin.DECLARATIVE_METADATA,
        reason="DECLARED_REQUIREMENT",
        citations=semantic.facts[0].citations,
        kind=kind,
        name="bounded prerequisite",
    )
    classified = result(semantic.model_copy(update={"requirements": (requirement,)}))
    assert reason in codes(classified)
    assert classified.classification is (
        SupportClassification.UNSUPPORTED
        if kind is RequirementKind.PRIVILEGE
        else SupportClassification.ASSISTED
    )


@pytest.mark.parametrize(
    "reason",
    [
        "PERSISTENCE_UNRESOLVED",
        "SELF_MODIFICATION_UNRESOLVED",
        "MASS_TARGET_UNRESOLVED",
        "OBFUSCATION_UNRESOLVED",
        "SOURCE_REWRITING_UNRESOLVED",
        "KERNEL_BEHAVIOR_UNRESOLVED",
        "INTERACTIVE_BEHAVIOR_UNRESOLVED",
        "UNREVIEWED_INSTALLER",
        "FUTURE_UNKNOWN_REASON",
    ],
)
def test_unmodeled_material_uncertainty_fails_closed(
    semantic: SemanticInspectionDocument, reason: str
) -> None:
    unknown = InspectionUnknown(
        item_id=identity(reason),
        source_path="checker.py",
        origin=SourceOrigin.CODE,
        reason=reason,
    )
    classified = result(semantic.model_copy(update={"unknowns": (unknown,)}))
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN in codes(classified)
    assert classified.blocking_unknown_refs == (unknown.item_id,)
    # There is no invented OBSERVED persistence/mass-target taxonomy or detector.


def test_inferred_privilege_is_uncertainty_not_observed_requirement(
    semantic: SemanticInspectionDocument,
) -> None:
    fact = semantic.facts[0]
    risk = RiskIndicator(
        item_id=identity("inferred privilege"),
        source_path="checker.py",
        origin=SourceOrigin.CODE,
        epistemic_state=EpistemicState.INFERRED,
        supporting_fact_refs=(fact.item_id,),
        reason="INFERRED_PRIVILEGE",
        citations=fact.citations,
        kind=RiskKind.PRIVILEGED_EXECUTION,
    )
    classified = result(semantic.model_copy(update={"risk_indicators": (risk,)}))
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN in codes(classified)
    assert ReasonCode.UNSUPPORTED_PRIVILEGED_EXECUTION not in codes(classified)


@pytest.mark.parametrize("runtime", ["powershell", "javascript"])
def test_unsupported_runtime_precedes_credentials(
    semantic: SemanticInspectionDocument, runtime: str
) -> None:
    candidate = semantic.entrypoint_candidates[0].model_copy(update={"runtime": runtime})
    credential = Requirement(
        item_id=identity("credential"),
        source_path="checker.py",
        origin=SourceOrigin.CODE,
        reason="CREDENTIAL_PARAMETER",
        citations=semantic.facts[0].citations,
        kind=RequirementKind.CREDENTIAL,
        name="credential",
    )
    classified = result(
        semantic.model_copy(
            update={
                "entrypoint_candidates": (candidate,),
                "requirements": (credential,),
            }
        )
    )
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert {ReasonCode.UNSUPPORTED_RUNTIME, ReasonCode.REQUIRES_CREDENTIAL} <= codes(classified)


@pytest.mark.parametrize(
    "status",
    [
        CoverageStatus.PARSER_FAILED,
        CoverageStatus.SKIPPED_BINARY,
        CoverageStatus.SKIPPED_ENCODING,
        CoverageStatus.SKIPPED_LIMIT,
        CoverageStatus.SKIPPED_UNSUPPORTED_TYPE,
        CoverageStatus.PARTIAL,
    ],
)
def test_unexplained_critical_coverage_never_automatic(
    semantic: SemanticInspectionDocument, status: CoverageStatus
) -> None:
    coverage = tuple(entry.model_copy(update={"status": status}) for entry in semantic.coverage)
    classified = result(semantic.model_copy(update={"coverage": coverage}))
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert classified.coverage.incomplete_material_paths == ("checker.py",)
    assert ReasonCode.UNSUPPORTED_INSUFFICIENT_COVERAGE in codes(classified)


def test_collection_truncation_blocks_even_without_remaining_unknowns(
    semantic: SemanticInspectionDocument,
) -> None:
    classified = result(semantic.model_copy(update={"limit_reasons": ("UNKNOWN_LIMIT",)}))
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert ReasonCode.UNSUPPORTED_INSUFFICIENT_COVERAGE in codes(classified)


def test_determinism_including_input_permutations(semantic: SemanticInspectionDocument) -> None:
    first = result(semantic)
    reversed_document = semantic.model_copy(
        update={
            "facts": tuple(reversed(semantic.facts)),
            "parameter_candidates": tuple(reversed(semantic.parameter_candidates)),
            "dependency_observations": tuple(reversed(semantic.dependency_observations)),
            "citations": tuple(reversed(semantic.citations)),
            "coverage": tuple(reversed(semantic.coverage)),
        }
    )
    assert semantic_digest(reversed_document) == semantic_digest(semantic)
    assert result(reversed_document).model_dump_json() == first.model_dump_json()
    assert SupportClassificationDocument.model_validate_json(first.model_dump_json()) == first
    assert SupportClassificationDocument.model_json_schema()["additionalProperties"] is False


def test_result_rejects_unknown_fields_codes_and_wrong_precedence(
    semantic: SemanticInspectionDocument,
) -> None:
    valid = result(semantic)
    for updates in (
        {"approved": True},
        {"argv": ["execute"]},
        {"classification": "UNSUPPORTED"},
        {"reasons": [{"code": "MODEL_SAYS_SAFE"}]},
    ):
        with pytest.raises(ValidationError):
            SupportClassificationDocument.model_validate(valid.model_dump() | updates)
    with pytest.raises(ValidationError):
        ClassificationReason(code=ReasonCode.REQUIRES_CREDENTIAL, item_refs=("z", "a"))


def test_fabricated_or_cross_input_reason_evidence_rejected(
    semantic: SemanticInspectionDocument,
) -> None:
    valid = result(semantic)
    original = valid.reasons[0]
    invalid = valid.model_copy(
        update={
            "reasons": (
                original.model_copy(update={"item_refs": (identity("not present"),)}),
                *valid.reasons[1:],
            )
        }
    )
    with pytest.raises(InspectionError, match="CLASSIFICATION_EVIDENCE_INVALID"):
        validate_classification_evidence(invalid, semantic)
    invalid = valid.model_copy(update={"semantic_document_sha256": "0" * 64})
    with pytest.raises(InspectionError, match="CLASSIFICATION_INPUT_CHANGED"):
        validate_classification_evidence(invalid, semantic)


def test_classifier_input_bounds(semantic: SemanticInspectionDocument) -> None:
    with pytest.raises(InspectionError, match="CLASSIFICATION_INPUT_LIMIT"):
        classify_support(REF, semantic, ClassifierConfiguration(max_input_items=1))


def test_runtime_candidate_without_grounded_python_fact_cannot_qualify(
    semantic: SemanticInspectionDocument,
) -> None:
    document = semantic.model_copy(
        update={
            "facts": tuple(fact for fact in semantic.facts if fact.kind != "PYTHON_SOURCE"),
        }
    )
    classified = result(document)
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN in codes(classified)


def test_unknown_blocker_cannot_be_unbound_or_hidden_in_automatic(
    semantic: SemanticInspectionDocument,
) -> None:
    valid = result(semantic)
    with pytest.raises(ValidationError, match="corresponding reason evidence"):
        SupportClassificationDocument.model_validate(
            valid.model_dump() | {"blocking_unknown_refs": (identity("hidden"),)}
        )


def test_profile_version_and_reason_identity_are_closed(
    semantic: SemanticInspectionDocument,
) -> None:
    valid = result(semantic)
    with pytest.raises(ValidationError):
        SupportClassificationDocument.model_validate(
            valid.model_dump() | {"classifier_version": "3"}
        )
    with pytest.raises(ValidationError):
        ClassifierConfiguration(max_input_items=True)


def test_material_unknown_precedes_credential_requirement(
    semantic: SemanticInspectionDocument,
) -> None:
    unknown = InspectionUnknown(
        item_id=identity("persistence gap"),
        source_path="checker.py",
        origin=SourceOrigin.CODE,
        reason="PERSISTENCE_UNRESOLVED",
    )
    credential = Requirement(
        item_id=identity("credential prerequisite"),
        source_path="checker.py",
        origin=SourceOrigin.CODE,
        reason="CREDENTIAL_PARAMETER",
        citations=semantic.facts[0].citations,
        kind=RequirementKind.CREDENTIAL,
        name="credential",
    )
    classified = result(
        semantic.model_copy(
            update={
                "unknowns": (unknown,),
                "requirements": (credential,),
            }
        )
    )
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert {ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN, ReasonCode.REQUIRES_CREDENTIAL} <= codes(
        classified
    )


def test_documentation_material_unknown_is_not_ignored_for_its_extension(
    semantic: SemanticInspectionDocument,
) -> None:
    from boberagent_core.inspections.semantic_models import FileCoverage

    claim = InspectionUnknown(
        item_id=identity("documented uncertainty"),
        source_path="README.md",
        origin=SourceOrigin.DOCUMENTATION,
        reason="PERSISTENCE_UNRESOLVED",
    )
    coverage = FileCoverage(
        path="README.md",
        status=CoverageStatus.PARTIAL,
        reason="EXTRACTOR_LIMITATIONS",
        extractor_id="documentation-claims",
        size_bytes=1,
        sha256="0" * 64,
    )
    classified = result(
        semantic.model_copy(
            update={
                "unknowns": (claim,),
                "coverage": (*semantic.coverage, coverage),
            }
        )
    )
    assert classified.classification is SupportClassification.ASSISTED
    assert ReasonCode.REQUIRES_DOCUMENTED_RISK_REVIEW in codes(classified)
    assert classified.assistance_unknown_refs == (claim.item_id,)
