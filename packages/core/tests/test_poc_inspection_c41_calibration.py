"""Offline syntactic scope calibration: no retained operator source or execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.inspections import (
    CorePoCSupportClassificationService,
    FileEffectScope,
    ReasonCode,
    SourceOrigin,
    SupportClassification,
    SupportClassificationDocument,
)
from boberagent_core.inspections.classification_models import ClassifierConfiguration
from boberagent_core.inspections.classifier import (
    classify_support,
    validate_classification_evidence,
)
from boberagent_core.inspections.semantic_models import BehaviorKind, EpistemicState, RiskKind
from test_poc_inspection_c2 import completed_document, prepare
from test_poc_inspection_c3 import CHECKER


@pytest.mark.parametrize(
    ("path", "source", "kind", "scope"),
    [
        (
            "code.py",
            b'import os\nos.remove("scratch.txt")',
            BehaviorKind.FILE_DELETE,
            FileEffectScope.BOUNDED,
        ),
        (
            "code.py",
            b'from pathlib import Path\nPath("scratch.txt").unlink()',
            BehaviorKind.FILE_DELETE,
            FileEffectScope.BOUNDED,
        ),
        ("code.py", b'open("report.txt", "w")', BehaviorKind.FILE_WRITE, FileEffectScope.BOUNDED),
        (
            "code.py",
            b'from pathlib import Path\nPath("report.txt").write_text("report")',
            BehaviorKind.FILE_WRITE,
            FileEffectScope.BOUNDED,
        ),
        (
            "code.py",
            b"import os\nos.unlink(destination)",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        ("code.py", b'open(destination, "w")', BehaviorKind.FILE_WRITE, FileEffectScope.UNKNOWN),
        (
            "code.py",
            b"from pathlib import Path\nPath(destination).unlink()",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "code.py",
            b'from pathlib import Path\np = Path("scratch.txt")\np.unlink()',
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "code.py",
            b'from pathlib import Path\nPath(destination).write_text("report")',
            BehaviorKind.FILE_WRITE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "code.py",
            b'import shutil\nshutil.rmtree("local-tree")',
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "code.py",
            b"import shutil\nshutil.rmtree(destination)",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "code.py",
            b'import shutil\nshutil.rmtree("/")',
            BehaviorKind.FILE_DELETE,
            FileEffectScope.BROAD,
        ),
        ("run.sh", b"rm scratch.txt", BehaviorKind.FILE_DELETE, FileEffectScope.BOUNDED),
        (
            "run.sh",
            b'tmp="/tmp/example.$$"\nrm "$tmp"',
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        ("run.sh", b'rm -rf "$destination"', BehaviorKind.FILE_DELETE, FileEffectScope.UNKNOWN),
        ("run.sh", b"rm -rf /", BehaviorKind.FILE_DELETE, FileEffectScope.BROAD),
        ("run.sh", b"rm -rf /*", BehaviorKind.FILE_DELETE, FileEffectScope.BROAD),
        ("run.sh", b"rm -rf '/*'", BehaviorKind.FILE_DELETE, FileEffectScope.UNKNOWN),
        (
            "code.py",
            b'import shutil\nshutil.rmtree("/*")',
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "run.ps1",
            b"Remove-Item -LiteralPath 'C:\\*' -Recurse",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        ("run.sh", b"echo rm -rf /", BehaviorKind.FILE_DELETE, FileEffectScope.UNKNOWN),
        (
            "run.ps1",
            b"Write-Output Remove-Item -Recurse /",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        ("run.sh", b"echo report > report.txt", BehaviorKind.FILE_WRITE, FileEffectScope.BOUNDED),
        (
            "run.sh",
            b'echo report > "$destination"',
            BehaviorKind.FILE_WRITE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "run.ps1",
            b"Remove-Item 'scratch.txt'",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.BOUNDED,
        ),
        (
            "run.ps1",
            b"Remove-Item $TemporaryFile",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.UNKNOWN,
        ),
        (
            "run.ps1",
            b"Remove-Item -Recurse -Force 'C:\\*'",
            BehaviorKind.FILE_DELETE,
            FileEffectScope.BROAD,
        ),
        ("run.ps1", b"Out-File 'report.txt'", BehaviorKind.FILE_WRITE, FileEffectScope.BOUNDED),
        (
            "run.ps1",
            b'Set-Content $Destination "report"',
            BehaviorKind.FILE_WRITE,
            FileEffectScope.UNKNOWN,
        ),
    ],
)
def test_filesystem_scope_is_evidence_not_primitive_risk(
    database: CoreDatabase,
    tmp_path: Path,
    path: str,
    source: bytes,
    kind: BehaviorKind,
    scope: FileEffectScope,
) -> None:
    service, request = prepare(database, tmp_path, {path: source})
    completed, document = completed_document(service, request)
    effects = [item for item in document.behavior_indicators if item.kind is kind]
    assert len(effects) == 1
    effect = effects[0]
    assert effect.file_effect_scope is scope
    assert effect.reason == f"FILE_EFFECT_SCOPE_{scope.value}"
    assert effect.origin is SourceOrigin.CODE
    assert effect.epistemic_state is EpistemicState.OBSERVED
    assert service.read_citation(completed.inspection_ref, effect.citations[0]) in source
    destructive = [
        item for item in document.risk_indicators if item.kind is RiskKind.DESTRUCTIVE_FILESYSTEM
    ]
    assert bool(destructive) is (scope is FileEffectScope.BROAD)
    unknowns = [item for item in document.unknowns if item.reason == "FILE_EFFECT_SCOPE_UNKNOWN"]
    assert bool(unknowns) is (scope is FileEffectScope.UNKNOWN)
    for item in (*destructive, *unknowns):
        assert item.citations == effect.citations
        assert item.origin is SourceOrigin.CODE
    classified = classify_support(completed.inspection_ref, document, ClassifierConfiguration())
    validate_classification_evidence(classified, document)
    codes = {item.code for item in classified.reasons}
    assert (ReasonCode.UNSUPPORTED_DESTRUCTIVE_BEHAVIOR in codes) is bool(destructive)
    assert (ReasonCode.UNSUPPORTED_UNBOUNDED_EFFECT in codes) is (scope is FileEffectScope.BROAD)
    if scope is FileEffectScope.UNKNOWN:
        assert classified.classification is SupportClassification.UNSUPPORTED
        assert ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN in codes
        assert {item.item_id for item in unknowns} <= set(classified.blocking_unknown_refs)
    elif scope is FileEffectScope.BOUNDED:
        assert ReasonCode.REQUIRES_FILESYSTEM_REVIEW in codes
    # Independent target-boundary gate must still reject these non-checker inputs.
    assert ReasonCode.UNSUPPORTED_ENTRYPOINT_UNKNOWN in codes


@pytest.mark.parametrize(
    ("extra", "expected", "required"),
    [
        (
            b'\nopen("report.txt", "w")\n',
            SupportClassification.ASSISTED,
            ReasonCode.REQUIRES_FILESYSTEM_REVIEW,
        ),
        (
            b'\nimport os\nos.remove("scratch.txt")\n',
            SupportClassification.ASSISTED,
            ReasonCode.REQUIRES_FILESYSTEM_REVIEW,
        ),
        (
            b'\nopen(destination, "w")\n',
            SupportClassification.UNSUPPORTED,
            ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN,
        ),
        (
            b'\nimport shutil\nshutil.rmtree("/")\n',
            SupportClassification.UNSUPPORTED,
            ReasonCode.UNSUPPORTED_DESTRUCTIVE_BEHAVIOR,
        ),
    ],
)
def test_calibrated_precedence_and_determinism(
    database: CoreDatabase,
    tmp_path: Path,
    extra: bytes,
    expected: SupportClassification,
    required: ReasonCode,
) -> None:
    service, request = prepare(database, tmp_path, {"checker.py": CHECKER + extra})
    c2, semantic = completed_document(service, request)
    again = service.create_semantic(
        mission_ref=c2.mission_ref,
        hypothesis_ref=c2.hypothesis_ref,
        candidate_ref=c2.candidate_ref,
        acquisition_ref=c2.acquisition_ref,
        force_new=True,
    )
    assert completed_document(service, again)[1] == semantic
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.classify(classifier.create(c2.inspection_ref).inspection_ref)
    assert isinstance(c3.document, SupportClassificationDocument)
    assert c2.profile_version == c3.profile_version == "2"
    assert c3.document.document_version == "m20-c3-support-classifier-v2"
    assert c3.document.classification is expected
    assert required in {item.code for item in c3.document.reasons}
    assert ReasonCode.UNSUPPORTED_TARGET_BOUNDARY not in {item.code for item in c3.document.reasons}
    validate_classification_evidence(c3.document, semantic)
    for reason in c3.document.reasons:
        assert reason.item_refs or reason.coverage_paths or reason.conflict_refs


@pytest.mark.parametrize("origin", [SourceOrigin.DOCUMENTATION, SourceOrigin.CODE])
def test_scope_claim_cannot_promote_documentation_or_inference(
    database: CoreDatabase,
    tmp_path: Path,
    origin: SourceOrigin,
) -> None:
    service, request = prepare(
        database, tmp_path, {"checker.py": CHECKER + b'\nopen("report.txt", "w")\n'}
    )
    c2, document = completed_document(service, request)
    effect = next(
        item for item in document.behavior_indicators if item.kind is BehaviorKind.FILE_WRITE
    )
    # Controlled typed fixture: not a claim that extractors infer these assertions.
    claim = effect.model_copy(
        update={
            "origin": origin,
            "epistemic_state": (
                EpistemicState.OBSERVED
                if origin is SourceOrigin.DOCUMENTATION
                else EpistemicState.INFERRED
            ),
            "supporting_fact_refs": (
                () if origin is SourceOrigin.DOCUMENTATION else (document.facts[0].item_id,)
            ),
            "reason": "FILE_EFFECT_SCOPE_BROAD",
        }
    )
    changed = document.model_copy(update={"behavior_indicators": (claim,)})
    classified = classify_support(c2.inspection_ref, changed, ClassifierConfiguration())
    validate_classification_evidence(classified, changed)
    codes = {reason.code for reason in classified.reasons}
    assert classified.classification is SupportClassification.UNSUPPORTED
    assert ReasonCode.UNSUPPORTED_MATERIAL_UNKNOWN in codes
    assert ReasonCode.UNSUPPORTED_UNBOUNDED_EFFECT not in codes
    assert ReasonCode.UNSUPPORTED_DESTRUCTIVE_BEHAVIOR not in codes
    assert not changed.risk_indicators
    assert any(claim.item_id in reason.item_refs for reason in classified.reasons)
