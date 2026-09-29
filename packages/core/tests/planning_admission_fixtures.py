"""Faithful migration-backed C1/C2/C3 chains over harmless retained synthetic bytes."""

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from boberagent_core import CoreDatabase
from boberagent_core.acquisitions.models import PoCAcquisition
from boberagent_core.inspections import CorePoCSupportClassificationService, PoCInspection
from boberagent_core.inspections.identity import PoCInspectionRef
from boberagent_core.planning.admission_models import PlanningAdmissionRequest
from test_poc_inspection_c2 import completed_document, prepare
from test_poc_inspection_c3 import CHECKER


@dataclass(frozen=True)
class AdmissionChain:
    acquisition: PoCAcquisition
    c2: PoCInspection
    c3: PoCInspection
    request: PlanningAdmissionRequest


def seed_chain(
    database: CoreDatabase, tmp_path: Path, files: dict[str, bytes] | None = None
) -> AdmissionChain:
    service, requested = prepare(database, tmp_path, files or {"checker.py": CHECKER})
    c2, _ = completed_document(service, requested)
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.classify(classifier.create(c2.inspection_ref).inspection_ref)
    with database.unit_of_work() as work:
        acquisition = work.acquisitions.get(c2.acquisition_ref)
    assert acquisition is not None
    return AdmissionChain(
        acquisition=acquisition,
        c2=c2,
        c3=c3,
        request=PlanningAdmissionRequest(
            mission_ref=c2.mission_ref,
            acquisition_ref=c2.acquisition_ref,
            semantic_inspection_ref=c2.inspection_ref,
            classification_inspection_ref=c3.inspection_ref,
            planner_profile="m20-d-planning",
            planner_version="1",
            policy_profile="m20-python-single-target",
            policy_version="1",
        ),
    )


def persist_inspection(
    database: CoreDatabase, original: PoCInspection, changes: dict[str, object]
) -> PoCInspection:
    """New typed records for negative boundaries, never rewrite completed history."""
    value = PoCInspection.model_validate(
        original.model_dump()
        | {"inspection_ref": PoCInspectionRef(f"poc-inspection-test-{uuid4().hex}")}
        | changes
    )
    with database.unit_of_work() as work:
        work.inspections.add(value)
    return value
