"""C1 creation requires one completed, correctly owned acquisition."""

from __future__ import annotations

from pathlib import Path

import pytest
from boberagent_contracts import MissionRef
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    CoreDatabase,
    FilesystemArtifactStorage,
)
from boberagent_core.acquisitions import CorePoCAcquisitionService, PoCAcquisitionStatus
from boberagent_core.inspections import CorePoCInspectionService, InspectionStatus
from boberagent_core.inspections.evidence import InspectionError
from boberagent_core.research.models import PoCCandidateRef, VulnerabilityHypothesisRef
from test_core_poc_acquisition import (
    NOW,
    _bounds,
    _dispatch,
    _persist_result,
    _receipt,
    _seed,
)
from test_poc_inspection_c1 import _setup


@pytest.mark.parametrize(
    "state",
    [
        PoCAcquisitionStatus.REQUESTED,
        PoCAcquisitionStatus.DISPATCHED,
        PoCAcquisitionStatus.AWAITING_ARTIFACT,
        PoCAcquisitionStatus.FAILED,
        PoCAcquisitionStatus.REJECTED,
        PoCAcquisitionStatus.INTERRUPTED,
    ],
)
def test_noncompleted_acquisition_cannot_start_inspection(
    database: CoreDatabase, tmp_path: Path, state: PoCAcquisitionStatus
) -> None:
    storage = FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts"))
    artifacts = CoreArtifactService(database, storage)
    acquisitions = CorePoCAcquisitionService(database, artifacts, clock=lambda: NOW)
    inspections = CorePoCInspectionService(database, artifacts, clock=lambda: NOW)
    _research, candidate, hits, hypothesis = _seed(database)
    acquisition = acquisitions.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate,
        selected_hit_id=hits[0],
        bounds=_bounds(),
    )
    if state in {PoCAcquisitionStatus.DISPATCHED, PoCAcquisitionStatus.AWAITING_ARTIFACT}:
        invocation = _dispatch(database, acquisitions, acquisition.acquisition_ref)
        if state is PoCAcquisitionStatus.AWAITING_ARTIFACT:
            _persist_result(database, _receipt(invocation))
            assert acquisitions.reconcile(acquisition.acquisition_ref).status is state
    elif state is PoCAcquisitionStatus.FAILED:
        acquisitions.fail(acquisition.acquisition_ref, "offline failure")
    elif state is PoCAcquisitionStatus.REJECTED:
        acquisitions.reject(acquisition.acquisition_ref, "offline rejection")
    elif state is PoCAcquisitionStatus.INTERRUPTED:
        acquisitions.interrupt(acquisition.acquisition_ref, "offline interruption")
    with pytest.raises(InspectionError, match="ACQUISITION_NOT_INSPECTABLE"):
        inspections.create(
            mission_ref=hypothesis.mission_ref,
            hypothesis_ref=hypothesis.hypothesis_ref,
            candidate_ref=candidate,
            acquisition_ref=acquisition.acquisition_ref,
        )


def test_inspection_cannot_cross_mission_or_candidate_owner(
    database: CoreDatabase, tmp_path: Path
) -> None:
    inspections, requested, _ = _setup(database, tmp_path)
    _research, other_candidate, _hits, other_hypothesis = _seed(
        database, mission_suffix="other-inspection"
    )
    cases: tuple[tuple[MissionRef, VulnerabilityHypothesisRef, PoCCandidateRef], ...] = (
        (other_hypothesis.mission_ref, requested.hypothesis_ref, requested.candidate_ref),
        (requested.mission_ref, other_hypothesis.hypothesis_ref, requested.candidate_ref),
        (requested.mission_ref, requested.hypothesis_ref, other_candidate),
    )
    for mission_ref, hypothesis_ref, candidate_ref in cases:
        with pytest.raises(InspectionError, match="ACQUISITION_NOT_INSPECTABLE"):
            inspections.create(
                mission_ref=mission_ref,
                hypothesis_ref=hypothesis_ref,
                candidate_ref=candidate_ref,
                acquisition_ref=requested.acquisition_ref,
            )
    stored = inspections.get(requested.inspection_ref)
    assert stored is not None and stored.status is InspectionStatus.REQUESTED
