"""Persisted ownership, source/version mismatches and safe strict-document rejection."""

from pathlib import Path
from uuid import uuid4

import pytest
from boberagent_contracts import (
    ArtifactRef,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    Observation,
    ObservationRef,
    PoCSourceAcquisitionReceipt,
)
from boberagent_core import CoreDatabase, CorePersistence, service_ref_for_endpoint
from boberagent_core.acquisitions.models import PoCAcquisitionStatus
from boberagent_core.inspections import (
    PoCInspection,
    SupportClassificationDocument,
)
from boberagent_core.inspections.classification_models import semantic_digest
from boberagent_core.inspections.semantic_models import SemanticInspectionDocument
from boberagent_core.planning.admission import CorePlanningAdmissionService
from boberagent_core.planning.admission_errors import PlanningAdmissionError
from planning_admission_fixtures import persist_inspection, seed_chain
from sqlalchemy import text
from test_core_poc_acquisition import NOW, _components, _dispatch, _seed
from test_planning_admission import counts
from test_poc_inspection_c3 import CHECKER
from test_poc_inspection_c41_history import seed_legacy_history


@pytest.mark.parametrize(
    "status", [item for item in PoCAcquisitionStatus if item is not PoCAcquisitionStatus.COMPLETED]
)
def test_non_completed_acquisition(
    database: CoreDatabase, tmp_path: Path, status: PoCAcquisitionStatus
) -> None:
    chain = seed_chain(database, tmp_path)
    service, _, _ = _components(database, tmp_path)
    a = chain.acquisition
    other = service.create_acquisition(
        mission_ref=a.mission_ref,
        hypothesis_ref=a.hypothesis_ref,
        candidate_ref=a.candidate_ref,
        selected_hit_id=a.selected_hit_id,
        bounds=a.bounds,
    )
    if status in {PoCAcquisitionStatus.DISPATCHED, PoCAcquisitionStatus.AWAITING_ARTIFACT}:
        invocation = _dispatch(
            database,
            service,
            other.acquisition_ref,
            run_ref=CapabilityRunRef(f"run-d3-{uuid4().hex}"),
        )
        with database.unit_of_work() as work:
            stored = work.acquisitions.get(other.acquisition_ref)
        assert stored is not None
        other = stored
        if status is PoCAcquisitionStatus.AWAITING_ARTIFACT:
            assert a.receipt is not None
            raw = a.receipt.raw_source.model_copy(
                update={
                    "artifact_id": ArtifactRef("artifact-d3-other-raw"),
                    "created_by_run": invocation.run_id,
                }
            )
            manifest = a.receipt.manifest.model_copy(
                update={
                    "artifact_id": ArtifactRef("artifact-d3-other-manifest"),
                    "created_by_run": invocation.run_id,
                }
            )
            receipt = PoCSourceAcquisitionReceipt.model_validate(
                a.receipt.model_dump()
                | {
                    "acquisition_ref": other.acquisition_ref,
                    "run_ref": invocation.run_id,
                    "raw_source": raw,
                    "manifest": manifest,
                }
            )
            with database.unit_of_work() as work:
                work.artifacts.add(raw)
                work.artifacts.add(manifest)
                work.acquisitions.update(
                    other.model_copy(update={"status": status, "receipt": receipt})
                )
    elif status is not PoCAcquisitionStatus.REQUESTED:
        with database.unit_of_work() as work:
            work.acquisitions.update(other.model_copy(update={"status": status}))
    with pytest.raises(PlanningAdmissionError, match="ACQUISITION_NOT_COMPLETED"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(update={"acquisition_ref": other.acquisition_ref})
        )
    assert counts(database)["planning_attempts"] == 0


@pytest.mark.parametrize("which", ["c2", "c3"])
@pytest.mark.parametrize(
    "field",
    [
        "acquisition_ref",
        "raw_artifact_ref",
        "manifest_artifact_ref",
        "raw_sha256",
        "manifest_sha256",
        "resolved_commit_sha",
        "raw_size_bytes",
    ],
)
def test_inspection_source_mismatch(
    database: CoreDatabase, tmp_path: Path, which: str, field: str
) -> None:
    chain = seed_chain(database, tmp_path)
    original = getattr(chain, which)
    if field == "acquisition_ref":
        service, _, _ = _components(database, tmp_path)
        a = chain.acquisition
        other = service.create_acquisition(
            mission_ref=a.mission_ref,
            hypothesis_ref=a.hypothesis_ref,
            candidate_ref=a.candidate_ref,
            selected_hit_id=a.selected_hit_id,
            bounds=a.bounds,
        )
        replacement: object = other.acquisition_ref
    elif field == "raw_artifact_ref":
        replacement = original.manifest_artifact_ref
    elif field == "manifest_artifact_ref":
        replacement = original.raw_artifact_ref
    elif field == "raw_size_bytes":
        replacement = original.raw_size_bytes + 1
    else:
        replacement = "f" * (40 if field == "resolved_commit_sha" else 64)
    # Keep citation/envelope pins mutually consistent so admission, not Pydantic, detects source mismatch.
    if which == "c2" and field in {
        "raw_sha256",
        "manifest_sha256",
        "raw_artifact_ref",
        "manifest_artifact_ref",
    }:
        assert isinstance(replacement, str)
        changed = PoCInspection.model_validate_json(
            original.model_dump_json().replace(str(getattr(original, field)), str(replacement))
        )
        value = persist_inspection(database, changed, {})
    else:
        value = persist_inspection(database, original, {field: replacement})
    key = "semantic_inspection_ref" if which == "c2" else "classification_inspection_ref"
    with pytest.raises(PlanningAdmissionError, match="SOURCE_MISMATCH"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(update={key: value.inspection_ref})
        )
    assert counts(database)["planning_attempts"] == 0


@pytest.mark.parametrize("which", ["c2", "c3"])
def test_cross_mission_inspection_even_with_identical_hashes(
    database: CoreDatabase, tmp_path: Path, which: str
) -> None:
    chain = seed_chain(database, tmp_path)
    _, _, _, other_hypothesis = _seed(database, mission_suffix="other")
    value = persist_inspection(
        database, getattr(chain, which), {"mission_ref": other_hypothesis.mission_ref}
    )
    key = "semantic_inspection_ref" if which == "c2" else "classification_inspection_ref"
    with pytest.raises(PlanningAdmissionError, match="OWNERSHIP_MISMATCH"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(update={key: value.inspection_ref})
        )


@pytest.mark.parametrize("which", ["asset", "candidate", "hypothesis", "service"])
def test_authoritative_relationship_ownership(
    database: CoreDatabase, tmp_path: Path, which: str
) -> None:
    chain = seed_chain(database, tmp_path)
    _, _, _, other = _seed(database, mission_suffix="other")
    if which == "service":
        core = CorePersistence(database)
        run = CapabilityRun(
            run_id=CapabilityRunRef("run-other-service"),
            mission_ref=other.mission_ref,
            capability_id="test.service",
            operation="discover",
            status=CapabilityRunStatus.COMPLETED,
            created_at=NOW,
            started_at=NOW,
            finished_at=NOW,
        )
        core.record_run(run)
        observation = Observation(
            observation_id=ObservationRef("observation-other-service"),
            type="network.service",
            subject_ref=other.asset_ref,
            value={"transport": "tcp", "port": 80, "state": "open"},
            run_ref=run.run_id,
            observed_at=NOW,
        )
        core.append_observation(observation)
        core.materialize_observation(observation.observation_id)
    # Explicit persisted-corruption injection: SQL FKs cannot protect cross-Mission semantic links.
    with database._migration_engine.begin() as connection:
        if which == "asset":
            connection.execute(
                text(
                    "UPDATE vulnerability_hypotheses SET asset_id=:asset WHERE hypothesis_id=:ref"
                ),
                {"asset": str(other.asset_ref), "ref": str(chain.acquisition.hypothesis_ref)},
            )
        elif which == "candidate":
            connection.execute(
                text("UPDATE poc_candidates SET hypothesis_id=:other WHERE candidate_id=:ref"),
                {"other": str(other.hypothesis_ref), "ref": str(chain.acquisition.candidate_ref)},
            )
        elif which == "hypothesis":
            connection.execute(
                text(
                    "UPDATE vulnerability_hypotheses SET mission_id=:mission WHERE hypothesis_id=:ref"
                ),
                {"mission": str(other.mission_ref), "ref": str(chain.acquisition.hypothesis_ref)},
            )
        else:
            connection.execute(
                text(
                    "UPDATE vulnerability_hypotheses SET service_id=:service WHERE hypothesis_id=:ref"
                ),
                {
                    "service": str(service_ref_for_endpoint(other.asset_ref, "tcp", 80)),
                    "ref": str(chain.acquisition.hypothesis_ref),
                },
            )
    with pytest.raises(PlanningAdmissionError, match="OWNERSHIP_MISMATCH"):
        CorePlanningAdmissionService(database).admit(chain.request)
    assert counts(database)["planning_attempts"] == 0


def test_historical_v1_remains_readable_not_admitted(
    database: CoreDatabase, tmp_path: Path
) -> None:
    chain = seed_chain(
        database, tmp_path, {"checker.py": CHECKER + b'\nimport os\nos.unlink("scratch.txt")\n'}
    )
    c2, c3 = seed_legacy_history(database, chain.c2)
    snapshots = (c2.model_dump_json(), c3.model_dump_json())
    with pytest.raises(PlanningAdmissionError, match="PROFILE_UNSUPPORTED"):
        CorePlanningAdmissionService(database).admit(
            chain.request.model_copy(
                update={
                    "semantic_inspection_ref": c2.inspection_ref,
                    "classification_inspection_ref": c3.inspection_ref,
                }
            )
        )
    with database.unit_of_work() as work:
        again2, again3 = (
            work.inspections.get(c2.inspection_ref),
            work.inspections.get(c3.inspection_ref),
        )
    assert again2 is not None and again3 is not None
    assert (again2.model_dump_json(), again3.model_dump_json()) == snapshots
    assert counts(database)["planning_attempts"] == 0


@pytest.mark.parametrize(
    "corruption",
    ["extra-field", "unknown-document", "unknown-profile", "bad-parent", "wrong-classification"],
)
def test_corrupt_persisted_c3_fails_safely(
    database: CoreDatabase, tmp_path: Path, corruption: str
) -> None:
    import json

    chain = seed_chain(database, tmp_path)
    assert isinstance(chain.c3.document, SupportClassificationDocument)
    document = chain.c3.document.model_dump(mode="json")
    if corruption == "extra-field":
        document["untrusted-secret"] = "untrusted-payload"
    elif corruption == "unknown-document":
        document["document_version"] = "future-classification"
    elif corruption == "unknown-profile":
        document["classifier_version"] = "3"
    elif corruption == "bad-parent":
        document["semantic_document_sha256"] = "f" * 64
    else:
        document["classification"] = "UNSUPPORTED"
    with database._migration_engine.begin() as connection:
        connection.execute(
            text("UPDATE poc_inspections SET document_json=:doc WHERE inspection_id=:ref"),
            {"doc": json.dumps(document), "ref": str(chain.c3.inspection_ref)},
        )
    with pytest.raises(PlanningAdmissionError, match="RECORD_INVALID") as error:
        CorePlanningAdmissionService(database).admit(chain.request)
    assert "untrusted" not in str(error.value)
    assert counts(database)["planning_attempts"] == 0


def test_metadata_only_artifact_is_not_admitted(database: CoreDatabase, tmp_path: Path) -> None:
    chain = seed_chain(database, tmp_path)
    with database._migration_engine.begin() as connection:
        connection.execute(
            text("UPDATE artifacts SET content_state='METADATA_ONLY' WHERE artifact_id=:ref"),
            {"ref": str(chain.c2.raw_artifact_ref)},
        )
    with pytest.raises(PlanningAdmissionError, match="ARTIFACT_MISMATCH"):
        CorePlanningAdmissionService(database).admit(chain.request)


def test_persisted_c2_change_invalidates_c3_parent(database: CoreDatabase, tmp_path: Path) -> None:
    import json

    chain = seed_chain(database, tmp_path)
    assert isinstance(chain.c2.document, SemanticInspectionDocument)
    before = semantic_digest(chain.c2.document)
    # Valid typed mutation simulates corrupted completed storage, never a service reinspection.
    document = SemanticInspectionDocument.model_validate(
        chain.c2.document.model_dump() | {"limit_reasons": ("SEMANTIC_BUDGET",)}
    )
    assert semantic_digest(document) != before
    with database._migration_engine.begin() as connection:
        connection.execute(
            text("UPDATE poc_inspections SET document_json=:doc WHERE inspection_id=:ref"),
            {
                "doc": json.dumps(document.model_dump(mode="json")),
                "ref": str(chain.c2.inspection_ref),
            },
        )
    with pytest.raises(PlanningAdmissionError, match="C3_PARENT_MISMATCH"):
        CorePlanningAdmissionService(database).admit(chain.request)


def test_retained_negative_categories_without_real_source(
    database: CoreDatabase, tmp_path: Path
) -> None:
    chain = seed_chain(
        database,
        tmp_path,
        {
            "checker.py": CHECKER
            + b'\nparser.add_argument("--url", required=True)\nunknown.connect()\n',
            "helper.bin": b"\x00\xff",
        },
    )
    result = CorePlanningAdmissionService(database, clock=lambda: NOW).admit(chain.request)
    codes = {
        reason.code.value for reason in result.attempt.request.inspection.classification.reasons
    }
    assert {
        "UNSUPPORTED_INSUFFICIENT_COVERAGE",
        "UNSUPPORTED_MATERIAL_UNKNOWN",
        "UNSUPPORTED_TARGET_BOUNDARY",
    } <= codes
    assert result.attempt.lifecycle.value == "COMPLETED"
    assert (
        result.attempt.disposition is not None and result.attempt.disposition.value == "UNSUPPORTED"
    )
    assert counts(database) == {
        "planning_attempts": 1,
        "execution_plans": 0,
        "plan_decisions": 0,
        "interactions": 0,
    }
