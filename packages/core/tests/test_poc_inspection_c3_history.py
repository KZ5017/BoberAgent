"""Immutable C3 input identity, bounds/history, recovery and no execution authority."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.inspections import (
    ClassifierConfiguration,
    CorePoCSupportClassificationService,
    InspectionError,
    InspectionStatus,
    SupportClassification,
    SupportClassificationDocument,
    classification_service,
    semantic_analysis,
)
from boberagent_core.inspections.classifier import classify_support
from boberagent_core.inspections.evidence import VerifiedSource
from boberagent_core.inspections.semantic_models import SemanticInspectionLimits
from boberagent_core.persistence.orm import PoCInspectionRow
from sqlalchemy.orm import Session
from test_poc_inspection_c2 import completed_document, prepare
from test_poc_inspection_c3 import CHECKER

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def test_reuse_config_and_parent_history(database: CoreDatabase, tmp_path: Path) -> None:
    service, c2_request = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, _ = completed_document(service, c2_request)
    classifier = CorePoCSupportClassificationService(database, clock=lambda: NOW)
    first = classifier.classify(classifier.create(c2.inspection_ref).inspection_ref)
    second = classifier.classify(
        classifier.create(c2.inspection_ref, force_new=True).inspection_ref
    )
    assert second.inspection_ref != first.inspection_ref and second.document == first.document
    changed = classifier.create(
        c2.inspection_ref, config=ClassifierConfiguration(max_input_items=3000)
    )
    assert changed.config_fingerprint != first.config_fingerprint
    assert changed.inspection_ref != first.inspection_ref
    another_c2 = service.create_semantic(
        mission_ref=c2.mission_ref,
        hypothesis_ref=c2.hypothesis_ref,
        candidate_ref=c2.candidate_ref,
        acquisition_ref=c2.acquisition_ref,
        force_new=True,
    )
    completed_document(service, another_c2)
    another_c3 = classifier.create(another_c2.inspection_ref)
    assert another_c3.config_fingerprint != first.config_fingerprint
    assert classifier.get(first.inspection_ref) == first
    with (
        database.unit_of_work() as work,
        pytest.raises(ValueError, match="illegal PoCInspection transition"),
    ):
        work.inspections.update(first.model_copy(update={"diagnostic": "rewrite history"}))


def test_restart_requested_and_interrupted_attempts(database: CoreDatabase, tmp_path: Path) -> None:
    service, c2_request = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, _ = completed_document(service, c2_request)
    classifier = CorePoCSupportClassificationService(database)
    requested = classifier.create(c2.inspection_ref)
    interrupted = classifier.create(c2.inspection_ref, force_new=True)
    with database.unit_of_work() as work:
        work.inspections.update(
            interrupted.model_copy(
                update={
                    "status": InspectionStatus.INSPECTING,
                    "started_at": NOW,
                }
            )
        )
    database.dispose()
    reopened = CoreDatabase(database.config)
    try:
        again = CorePoCSupportClassificationService(reopened)
        recovered = again.recover_interrupted()
        assert len(recovered) == 1
        assert recovered[0].inspection_ref == interrupted.inspection_ref
        assert recovered[0].status is InspectionStatus.INTERRUPTED
        assert recovered[0].document is None
        assert again.get(requested.inspection_ref) == requested
        assert again.classify(requested.inspection_ref).status is InspectionStatus.COMPLETED
        assert again.recover_interrupted() == ()
        with pytest.raises(InspectionError, match="INSPECTION_NOT_REQUESTED"):
            again.classify(interrupted.inspection_ref)
    finally:
        reopened.dispose()


def test_requires_persisted_completed_c2_not_c1(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    classifier = CorePoCSupportClassificationService(database)
    with pytest.raises(InspectionError, match="CLASSIFICATION_INPUT_NOT_COMPLETED_C2"):
        classifier.create(requested.inspection_ref)
    c1 = service.create(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=("checker.py",),
    )
    service.inspect(c1.inspection_ref)
    with pytest.raises(InspectionError, match="CLASSIFICATION_INPUT_NOT_COMPLETED_C2"):
        classifier.create(c1.inspection_ref)


def test_input_collection_limit_persists_failed_not_a_classification(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, _ = completed_document(service, requested)
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.create(c2.inspection_ref, config=ClassifierConfiguration(max_input_items=1))
    failed = classifier.classify(c3.inspection_ref)
    assert failed.status is InspectionStatus.FAILED and failed.document is None
    assert failed.diagnostic == "CLASSIFICATION_INPUT_LIMIT"
    assert (
        classifier.create(
            c2.inspection_ref, config=ClassifierConfiguration(max_input_items=1)
        ).inspection_ref
        != failed.inspection_ref
    )


def test_internal_bug_is_safe_durable_failure(
    database: CoreDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, _ = completed_document(service, requested)
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.create(c2.inspection_ref)

    def broken(*args: object, **kwargs: object) -> SupportClassificationDocument:
        raise RuntimeError("sensitive-hostile-source-text")

    monkeypatch.setattr(classification_service, "classify_support", broken)
    with pytest.raises(InspectionError, match=r"^CLASSIFIER_INTERNAL_ERROR$"):
        classifier.classify(c3.inspection_ref)
    failed = classifier.get(c3.inspection_ref)
    assert failed is not None and failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == "CLASSIFIER_INTERNAL_ERROR"
    assert "sensitive-hostile-source-text" not in failed.model_dump_json()


def test_c3_never_reopens_evidence_or_extracts_source(
    database: CoreDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, _ = completed_document(service, requested)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("C3 accessed source, network or execution machinery")

    monkeypatch.setattr(VerifiedSource, "__init__", forbidden)
    monkeypatch.setattr(service, "inspect", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    # The C2 extractor itself is not needed by C3 (also guarded statically).
    monkeypatch.setattr(semantic_analysis, "analyze_semantics", forbidden)
    classifier = CorePoCSupportClassificationService(database)
    result = classifier.classify(classifier.create(c2.inspection_ref).inspection_ref)
    assert result.status is InspectionStatus.COMPLETED


def test_c3_not_sent_through_the_evidence_inspection_pump(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, _ = completed_document(service, requested)
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.create(c2.inspection_ref)
    with pytest.raises(InspectionError, match="USE_CLASSIFICATION_SERVICE"):
        service.inspect(c3.inspection_ref)
    assert classifier.get(c3.inspection_ref) == c3


def test_material_c2_limit_completes_unsupported(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested = prepare(
        database, tmp_path, {"checker.py": CHECKER}, SemanticInspectionLimits(max_facts=1)
    )
    c2, _ = completed_document(service, requested)
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.classify(classifier.create(c2.inspection_ref).inspection_ref)
    assert c3.status is InspectionStatus.COMPLETED
    assert isinstance(c3.document, SupportClassificationDocument)
    assert c3.document.classification.value == "UNSUPPORTED"


def test_changed_persisted_c2_input_cannot_be_silently_reused(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, _ = completed_document(service, requested)
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.create(c2.inspection_ref)
    # Simulate out-of-band DB corruption; there is no public semantic update API.
    with Session(database._migration_engine) as session, session.begin():
        row = session.get(PoCInspectionRow, str(c2.inspection_ref))
        assert row is not None and row.document_json is not None
        row.document_json = row.document_json | {"limit_reasons": ["UNKNOWN_LIMIT"]}
    failed = classifier.classify(c3.inspection_ref)
    assert failed.status is InspectionStatus.FAILED and failed.document is None
    assert failed.diagnostic == "CLASSIFICATION_INPUT_CHANGED"


def test_invalid_classifier_output_is_not_published_as_completed(
    database: CoreDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, requested = prepare(database, tmp_path, {"checker.py": CHECKER})
    c2, semantic = completed_document(service, requested)
    classifier = CorePoCSupportClassificationService(database)
    request = classifier.create(c2.inspection_ref)
    valid = classify_support(c2.inspection_ref, semantic, ClassifierConfiguration())

    def malformed(*args: object, **kwargs: object) -> SupportClassificationDocument:
        return valid.model_copy(update={"classification": SupportClassification.ASSISTED})

    monkeypatch.setattr(classification_service, "classify_support", malformed)
    with pytest.raises(InspectionError, match="CLASSIFIER_INTERNAL_ERROR"):
        classifier.classify(request.inspection_ref)
    failed = classifier.get(request.inspection_ref)
    assert failed is not None and failed.status is InspectionStatus.FAILED
    assert failed.document is None and failed.diagnostic == "CLASSIFIER_INTERNAL_ERROR"
