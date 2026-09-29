"""D3 stops at authoritative admission; all source inspection is fixture setup only."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from boberagent_contracts import MissionRef, PoCAcquisitionRef
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_core import CoreArtifactService, CoreDatabase, Mission
from boberagent_core.inspections import (
    CorePoCInspectionService,
    CorePoCSupportClassificationService,
    InspectionStatus,
    SemanticInspectionDocument,
    SupportClassificationDocument,
)
from boberagent_core.inspections.classification_models import (
    ClassificationInspectionLimits,
    ClassifierConfiguration,
    semantic_digest,
)
from boberagent_core.inspections.config_identity import classification_config_fingerprint
from boberagent_core.inspections.models import InspectionDocument
from boberagent_core.planning import (
    PlanningAdmissionOutcome,
    PlanningAdmissionRequest,
    PlanningAttemptLifecycle,
    PlanningDisposition,
    planning_request_fingerprint,
)
from boberagent_core.planning import admission as admission_module
from boberagent_core.planning.admission import CorePlanningAdmissionService
from boberagent_core.planning.admission_errors import AdmissionErrorCode, PlanningAdmissionError
from planning_admission_fixtures import persist_inspection, seed_chain
from pydantic import ValidationError
from sqlalchemy import text
from test_core_poc_acquisition import NOW
from test_poc_inspection_c3 import CHECKER


def counts(database: CoreDatabase) -> dict[str, int]:
    with database._migration_engine.connect() as connection:
        return {
            name: int(connection.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one())
            for name in ("planning_attempts", "execution_plans", "plan_decisions", "interactions")
        }


def deny(*args: object, **kwargs: object) -> None:
    raise AssertionError("D3 must not access source or run inspection/classification")


@pytest.mark.parametrize(
    ("files", "outcome"),
    [
        ({"checker.py": CHECKER}, PlanningAdmissionOutcome.ELIGIBLE_AUTOMATIC),
        (
            {"checker.py": CHECKER + b'\nparser.add_argument("--password", required=True)\n'},
            PlanningAdmissionOutcome.ELIGIBLE_ASSISTED,
        ),
        (
            {
                "checker.py": CHECKER
                + b'\nparser.add_argument("--password", required=True)\nunknown.connect()\n',
                "helper.bin": b"\x00\xff",
                "README.md": b"No credentials required.\n",
            },
            PlanningAdmissionOutcome.REJECTED_UNSUPPORTED,
        ),
    ],
)
def test_authoritative_admission_all_paths_reopen_reuse(
    database: CoreDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, bytes],
    outcome: PlanningAdmissionOutcome,
) -> None:
    chain = seed_chain(database, tmp_path, files)
    assert isinstance(chain.c2.document, SemanticInspectionDocument)
    assert isinstance(chain.c3.document, SupportClassificationDocument)
    # Production admission has no Artifact service dependency. Enforce no reader or reinspection.
    monkeypatch.setattr(CoreArtifactService, "open_content", deny)
    monkeypatch.setattr(CorePoCInspectionService, "inspect", deny)
    monkeypatch.setattr(CorePoCInspectionService, "read_citation", deny)
    monkeypatch.setattr(CorePoCSupportClassificationService, "classify", deny)
    service = CorePlanningAdmissionService(database, clock=lambda: NOW)
    result = service.admit(chain.request)
    assert result.outcome is outcome
    attempt = result.attempt
    assert attempt.request.proposal is None and attempt.revisions == ()
    assert attempt.finalized_plan is None
    assert attempt.request.hypothesis_ref == chain.acquisition.hypothesis_ref
    assert attempt.request.candidate_ref == chain.acquisition.candidate_ref
    pins = attempt.request.inspection
    assert pins.classification == chain.c3.document
    assert pins.classification.semantic_document_sha256 == semantic_digest(chain.c2.document)
    assert pins.classification_sha256 == canonical_digest(chain.c3.document)
    assert pins.classification_sha256 != pins.classification.semantic_document_sha256
    assert chain.acquisition.receipt is not None
    source = attempt.request.source
    receipt = chain.acquisition.receipt
    assert (source.raw_artifact_ref, source.raw_sha256, source.raw_size_bytes) == (
        receipt.raw_source.artifact_id,
        receipt.raw_archive_sha256,
        receipt.raw_archive_size_bytes,
    )
    assert (source.manifest_artifact_ref, source.manifest_sha256, source.resolved_commit) == (
        receipt.manifest.artifact_id,
        receipt.manifest_sha256,
        receipt.resolved_commit_sha,
    )
    if outcome is PlanningAdmissionOutcome.REJECTED_UNSUPPORTED:
        assert attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
        assert attempt.disposition is PlanningDisposition.UNSUPPORTED
        assert attempt.completed_at == NOW
        assert pins.classification.blocking_unknown_refs
        assert pins.classification.blocking_conflict_refs
        assert any(
            reason.code.value.startswith("REQUIRES_") for reason in pins.classification.reasons
        )
    else:
        assert attempt.lifecycle is PlanningAttemptLifecycle.REQUESTED
        assert attempt.disposition is None and attempt.completed_at is None
    assert service.admit(chain.request) == result
    database.dispose()
    reopened = CoreDatabase(database.config)
    try:
        again = CorePlanningAdmissionService(reopened, clock=lambda: NOW)
        assert again.get_admission(attempt.planning_attempt_ref) == result
        assert again.admit(chain.request) == result
        assert counts(reopened) == {
            "planning_attempts": 1,
            "execution_plans": 0,
            "plan_decisions": 0,
            "interactions": 0,
        }
    finally:
        reopened.dispose()


@pytest.mark.parametrize(
    "field",
    [
        "classification",
        "blockers",
        "raw_sha256",
        "semantic_document_sha256",
        "classification_sha256",
        "hypothesis_ref",
        "candidate_ref",
        "proposal",
        "document",
    ],
)
def test_caller_cannot_supply_truth(database: CoreDatabase, tmp_path: Path, field: str) -> None:
    chain = seed_chain(database, tmp_path)
    with pytest.raises(ValidationError):
        PlanningAdmissionRequest.model_validate(chain.request.model_dump() | {field: "tampered"})
    bypass = chain.request.model_copy(update={field: "tampered"})
    with pytest.raises(PlanningAdmissionError, match="REQUEST_INVALID"):
        CorePlanningAdmissionService(database).admit(bypass)
    assert counts(database)["planning_attempts"] == 0


def test_wrong_mission_and_unknown_acquisition(database: CoreDatabase, tmp_path: Path) -> None:
    chain = seed_chain(database, tmp_path)
    other = MissionRef("mission-d3-other")
    with database.unit_of_work() as work:
        work.missions.add(Mission(mission_ref=other, status="ACTIVE", created_at=NOW))
    service = CorePlanningAdmissionService(database)
    with pytest.raises(PlanningAdmissionError, match="OWNERSHIP_MISMATCH"):
        service.admit(chain.request.model_copy(update={"mission_ref": other}))
    with pytest.raises(PlanningAdmissionError, match="UPSTREAM_NOT_FOUND"):
        service.admit(
            chain.request.model_copy(update={"acquisition_ref": PoCAcquisitionRef("missing")})
        )
    assert counts(database)["planning_attempts"] == 0


@pytest.mark.parametrize("which", ["c2", "c3"])
@pytest.mark.parametrize(
    "status",
    [
        InspectionStatus.REQUESTED,
        InspectionStatus.INSPECTING,
        InspectionStatus.FAILED,
        InspectionStatus.INTERRUPTED,
    ],
)
def test_non_completed_inspections(
    database: CoreDatabase, tmp_path: Path, which: str, status: InspectionStatus
) -> None:
    chain = seed_chain(database, tmp_path)
    value = persist_inspection(
        database,
        getattr(chain, which),
        {
            "status": status,
            "document": None,
            "started_at": None if status is InspectionStatus.REQUESTED else NOW,
            "finished_at": NOW if status.is_terminal else None,
        },
    )
    field = "semantic_inspection_ref" if which == "c2" else "classification_inspection_ref"
    with pytest.raises(PlanningAdmissionError, match=f"{which.upper()}_NOT_COMPLETED"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(update={field: value.inspection_ref})
        )
    assert counts(database)["planning_attempts"] == 0


@pytest.mark.parametrize("which", ["c2", "c3"])
@pytest.mark.parametrize("version", ["1", "3"])
def test_unknown_profile_fails_closed(
    database: CoreDatabase, tmp_path: Path, which: str, version: str
) -> None:
    chain = seed_chain(database, tmp_path)
    # A valid other-profile document is readable but not authoritative C2/C3@2.
    value = persist_inspection(
        database,
        getattr(chain, which),
        {
            "profile_id": "other-inspector",
            "profile_version": version,
            "document": InspectionDocument(manifest_validated=True, zip_reconciled=True),
        },
    )
    field = "semantic_inspection_ref" if which == "c2" else "classification_inspection_ref"
    with pytest.raises(PlanningAdmissionError, match="PROFILE_UNSUPPORTED"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(update={field: value.inspection_ref})
        )


@pytest.mark.parametrize("which", ["c2", "c3"])
def test_configuration_fingerprint_mismatch(
    database: CoreDatabase, tmp_path: Path, which: str
) -> None:
    chain = seed_chain(database, tmp_path)
    value = persist_inspection(database, getattr(chain, which), {"config_fingerprint": "0" * 64})
    field = "semantic_inspection_ref" if which == "c2" else "classification_inspection_ref"
    with pytest.raises(PlanningAdmissionError, match="CONFIGURATION_MISMATCH"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(update={field: value.inspection_ref})
        )


@pytest.mark.parametrize("change_parent_ref", [False, True])
def test_c3_parent_binding_mismatch(
    database: CoreDatabase, tmp_path: Path, change_parent_ref: bool
) -> None:
    chain = seed_chain(database, tmp_path)
    assert isinstance(chain.c3.document, SupportClassificationDocument)
    assert isinstance(chain.c3.limits, ClassificationInspectionLimits)
    if change_parent_ref:
        alternate = persist_inspection(database, chain.c2, {})
        changes: dict[str, object] = {"semantic_inspection_ref": alternate.inspection_ref}
    else:
        changes = {"semantic_document_sha256": "0" * 64}
    limits = ClassificationInspectionLimits.model_validate(chain.c3.limits.model_dump() | changes)
    doc = SupportClassificationDocument.model_validate(chain.c3.document.model_dump() | changes)
    value = persist_inspection(
        database,
        chain.c3,
        {
            "limits": limits,
            "document": doc,
            "config_fingerprint": classification_config_fingerprint(limits),
        },
    )
    with pytest.raises(PlanningAdmissionError, match="C3_PARENT_MISMATCH"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(update={"classification_inspection_ref": value.inspection_ref})
        )
    assert counts(database)["planning_attempts"] == 0


def test_internal_failure_rolls_back_entire_admission(
    database: CoreDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = seed_chain(database, tmp_path, {"checker.py": CHECKER + b"\nunknown.connect()\n"})
    original = admission_module._result

    def fail_after_write(*args: object, **kwargs: object) -> None:
        # Fail after insertion and both lifecycle writes, before the outer UoW commits.
        raise RuntimeError("untrusted exception text must not escape")

    monkeypatch.setattr(admission_module, "_result", fail_after_write)
    with pytest.raises(PlanningAdmissionError) as captured:
        CorePlanningAdmissionService(database, clock=lambda: NOW).admit(chain.request)
    assert captured.value.code is AdmissionErrorCode.INTERNAL_ERROR
    assert "untrusted" not in str(captured.value)
    assert counts(database)["planning_attempts"] == 0
    monkeypatch.setattr(admission_module, "_result", original)
    assert (
        CorePlanningAdmissionService(database, clock=lambda: NOW)
        .admit(chain.request)
        .attempt.lifecycle
        is PlanningAttemptLifecycle.COMPLETED
    )


@pytest.mark.parametrize("unsupported", [False, True])
def test_concurrent_independent_uows_reuse_one_attempt(
    database: CoreDatabase, tmp_path: Path, unsupported: bool
) -> None:
    chain = seed_chain(
        database,
        tmp_path,
        {
            "checker.py": CHECKER + (b"\nunknown.connect()\n" if unsupported else b""),
        },
    )
    barrier = Barrier(2)

    def admit() -> str:
        independent = CoreDatabase(database.config)
        try:
            barrier.wait(timeout=10)
            result = CorePlanningAdmissionService(independent, clock=lambda: NOW).admit(
                chain.request
            )
            return str(result.attempt.planning_attempt_ref)
        finally:
            independent.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(admit), executor.submit(admit)
        assert first.result(timeout=15) == second.result(timeout=15)
    assert counts(database) == {
        "planning_attempts": 1,
        "execution_plans": 0,
        "plan_decisions": 0,
        "interactions": 0,
    }


def test_new_authoritative_history_and_policy_change_identity(
    database: CoreDatabase, tmp_path: Path
) -> None:
    chain = seed_chain(
        database, tmp_path, {"checker.py": CHECKER, "README.md": b"Synthetic example\n"}
    )
    admission = CorePlanningAdmissionService(database, clock=lambda: NOW)
    first = admission.admit(chain.request)
    classifier = CorePoCSupportClassificationService(database)
    changed = classifier.classify(
        classifier.create(
            chain.c2.inspection_ref, config=ClassifierConfiguration(max_input_items=5000)
        ).inspection_ref
    )
    second = admission.admit(
        chain.request.model_copy(update={"classification_inspection_ref": changed.inspection_ref})
    )
    assert first.attempt.planning_attempt_ref != second.attempt.planning_attempt_ref
    assert planning_request_fingerprint(first.attempt.request) != planning_request_fingerprint(
        second.attempt.request
    )
    third = admission.admit(chain.request.model_copy(update={"policy_version": "2"}))
    assert third.attempt.planning_attempt_ref not in {
        first.attempt.planning_attempt_ref,
        second.attempt.planning_attempt_ref,
    }
    # Real new C2/C3 output on the same source, not a caller-supplied classification document.
    from boberagent_core import ArtifactStorageConfiguration, FilesystemArtifactStorage

    service = CorePoCInspectionService(
        database,
        CoreArtifactService(
            database,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
        ),
    )
    c2 = service.inspect(
        service.create_semantic(
            mission_ref=chain.c2.mission_ref,
            hypothesis_ref=chain.c2.hypothesis_ref,
            candidate_ref=chain.c2.candidate_ref,
            acquisition_ref=chain.c2.acquisition_ref,
            selected_paths=("checker.py",),
        ).inspection_ref
    )
    c3 = classifier.classify(classifier.create(c2.inspection_ref).inspection_ref)
    fourth = admission.admit(
        chain.request.model_copy(
            update={
                "semantic_inspection_ref": c2.inspection_ref,
                "classification_inspection_ref": c3.inspection_ref,
            }
        )
    )
    assert (
        fourth.attempt.request.inspection.classification_sha256
        != first.attempt.request.inspection.classification_sha256
    )
    assert planning_request_fingerprint(fourth.attempt.request) != planning_request_fingerprint(
        first.attempt.request
    )
