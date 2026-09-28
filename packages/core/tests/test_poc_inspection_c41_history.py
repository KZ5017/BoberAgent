"""V1 persisted shapes remain immutable; v2 attempts never reinterpret them."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    CoreDatabase,
    FilesystemArtifactStorage,
)
from boberagent_core.inspections import (
    ClassificationInspectionLimits,
    ClassificationReason,
    CorePoCInspectionService,
    CorePoCSupportClassificationService,
    InspectionError,
    PoCInspection,
    PoCInspectionRef,
    ReasonCode,
    SemanticInspectionDocument,
    SupportClassification,
    SupportClassificationDocument,
)
from boberagent_core.inspections.classification_models import semantic_digest
from boberagent_core.inspections.classifier import (
    classify_support,
    validate_classification_evidence,
)
from boberagent_core.inspections.semantic_models import BehaviorKind, RiskIndicator, RiskKind
from test_poc_inspection_c2 import completed_document, prepare
from test_poc_inspection_c3 import CHECKER


def seed_legacy_history(
    database: CoreDatabase, current: PoCInspection
) -> tuple[PoCInspection, PoCInspection]:
    """Seed the old supported JSON shape, including its primitive-only strong risk.

    This is synthetic persisted history, not execution of a retired extractor.
    """
    assert isinstance(current.document, SemanticInspectionDocument)
    data = current.document.model_dump(mode="json")
    data["document_version"] = "m20-c2-deterministic-v1"
    for effect in data["behavior_indicators"]:
        if effect["kind"] in {"FILE_WRITE", "FILE_DELETE"}:
            effect["reason"] = "SOURCE_SYNTAX_INDICATOR"
    effect = next(
        item
        for item in current.document.behavior_indicators
        if item.kind is BehaviorKind.FILE_DELETE
    )
    risk = RiskIndicator(
        **(
            effect.model_dump(exclude={"kind"})
            | {
                "item_id": "item-" + hashlib.sha256(b"legacy primitive risk").hexdigest(),
                "reason": "SOURCE_SYNTAX_RISK",
            }
        ),
        kind=RiskKind.DESTRUCTIVE_FILESYSTEM,
    )
    data["risk_indicators"] = [risk.model_dump(mode="json")]
    old_semantic = SemanticInspectionDocument.model_validate(data)
    # Reader/coverage version values in old persisted documents stay v1 too.
    old_semantic = SemanticInspectionDocument.model_validate_json(
        old_semantic.model_dump_json()
        .replace('"reader_version":"2"', '"reader_version":"1"')
        .replace('"extractor_version":"2"', '"extractor_version":"1"')
    )
    old_c2 = PoCInspection.model_validate(
        current.model_dump()
        | {
            "inspection_ref": PoCInspectionRef("poc-inspection-history-c2-v1"),
            "profile_version": "1",
            "document": old_semantic,
        }
    )
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.classify(classifier.create(current.inspection_ref).inspection_ref)
    assert isinstance(c3.document, SupportClassificationDocument)
    digest = semantic_digest(old_semantic)
    old_document = SupportClassificationDocument.model_validate(
        c3.document.model_dump()
        | {
            "document_version": "m20-c3-support-classifier-v1",
            "classifier_version": "1",
            "semantic_inspection_ref": old_c2.inspection_ref,
            "semantic_document_sha256": digest,
            "classification": SupportClassification.UNSUPPORTED,
            "reasons": (
                ClassificationReason(
                    code=ReasonCode.UNSUPPORTED_DESTRUCTIVE_BEHAVIOR, item_refs=(risk.item_id,)
                ),
                ClassificationReason(
                    code=ReasonCode.UNSUPPORTED_UNBOUNDED_EFFECT, item_refs=(effect.item_id,)
                ),
            ),
            "blocking_unknown_refs": (),
            "assistance_unknown_refs": (),
        }
    )
    assert isinstance(c3.limits, ClassificationInspectionLimits)
    limits = c3.limits.model_copy(
        update={
            "semantic_inspection_ref": old_c2.inspection_ref,
            "semantic_document_sha256": digest,
        }
    )
    old_c3 = PoCInspection.model_validate(
        c3.model_dump()
        | {
            "inspection_ref": PoCInspectionRef("poc-inspection-history-c3-v1"),
            "profile_version": "1",
            "document": old_document,
            "limits": limits,
        }
    )
    validate_classification_evidence(old_document, old_semantic)
    with database.unit_of_work() as work:
        work.inspections.add(old_c2)
        work.inspections.add(old_c3)
    return old_c2, old_c3


def test_v1_json_and_digest_unchanged_after_reopen_and_v2_reuse(
    database: CoreDatabase,
    tmp_path: Path,
) -> None:
    service, request = prepare(
        database,
        tmp_path,
        {
            "checker.py": CHECKER + b'\nimport os\nos.unlink("scratch.txt")\n',
        },
    )
    current, _ = completed_document(service, request)
    old_c2, old_c3 = seed_legacy_history(database, current)
    snapshots = (old_c2.model_dump_json(), old_c3.model_dump_json())
    assert isinstance(old_c2.document, SemanticInspectionDocument)
    digest = semantic_digest(old_c2.document)
    database.dispose()
    reopened = CoreDatabase(database.config)
    try:
        again = CorePoCInspectionService(
            reopened,
            CoreArtifactService(
                reopened,
                FilesystemArtifactStorage(
                    ArtifactStorageConfiguration(root=tmp_path / "artifacts")
                ),
            ),
        )
        classifier = CorePoCSupportClassificationService(reopened)
        assert again.inspect(old_c2.inspection_ref).model_dump_json() == snapshots[0]
        assert classifier.classify(old_c3.inspection_ref).model_dump_json() == snapshots[1]
        assert semantic_digest(old_c2.document) == digest
        with pytest.raises(InspectionError, match="CLASSIFICATION_INPUT_PROFILE_UNSUPPORTED"):
            classifier.create(old_c2.inspection_ref)
        assert isinstance(old_c3.document, SupportClassificationDocument)
        assert isinstance(old_c3.limits, ClassificationInspectionLimits)
        with pytest.raises(InspectionError, match="CLASSIFICATION_INPUT_PROFILE_UNSUPPORTED"):
            classify_support(
                old_c2.inspection_ref, old_c2.document, old_c3.limits.classifier_config
            )
        v2 = again.create_semantic(
            mission_ref=current.mission_ref,
            hypothesis_ref=current.hypothesis_ref,
            candidate_ref=current.candidate_ref,
            acquisition_ref=current.acquisition_ref,
        )
        assert v2 == current and v2.inspection_ref != old_c2.inspection_ref
        c3 = classifier.classify(classifier.create(v2.inspection_ref).inspection_ref)
        assert isinstance(c3.document, SupportClassificationDocument)
        assert (
            c3.profile_version == "2"
            and c3.document.classification is SupportClassification.ASSISTED
        )
        assert old_c2.model_dump_json() == snapshots[0]
        assert old_c3.model_dump_json() == snapshots[1]
        with reopened.unit_of_work() as work, pytest.raises(ValueError, match="illegal"):
            work.inspections.update(old_c3.model_copy(update={"diagnostic": "rewrite"}))
    finally:
        reopened.dispose()


def test_target_boundary_unchanged_with_bounded_filesystem_mutation(
    database: CoreDatabase,
    tmp_path: Path,
) -> None:
    service, request = prepare(
        database,
        tmp_path,
        {
            "checker.py": b'open("report.txt", "w")\nif __name__ == "__main__":\n    pass\n',
        },
    )
    c2, document = completed_document(service, request)
    from boberagent_core.inspections.classification_models import ClassifierConfiguration

    result = classify_support(c2.inspection_ref, document, ClassifierConfiguration())
    assert result.classification is SupportClassification.UNSUPPORTED
    assert ReasonCode.UNSUPPORTED_TARGET_BOUNDARY in {reason.code for reason in result.reasons}
    assert ReasonCode.UNSUPPORTED_UNBOUNDED_EFFECT not in {reason.code for reason in result.reasons}
