"""B3 ordering and foreign-Node reconciliation remain fail-closed."""

from __future__ import annotations

from pathlib import Path

from boberagent_contracts import (
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
)
from boberagent_core import CoreDatabase, ResultIngestionService
from boberagent_core.acquisitions import PoCAcquisitionStatus
from test_core_poc_acquisition import (
    MANIFEST,
    NOW,
    RAW,
    _bounds,
    _components,
    _dispatch,
    _persist_result,
    _publish,
    _receipt,
    _seed,
)


def test_artifacts_available_before_result_finalize_without_new_run(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, storage, artifacts = _components(database, tmp_path)
    _research, candidate_ref, hits, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hits[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    receipt = _receipt(invocation)
    _publish(database, storage, receipt.raw_source, RAW)
    _publish(database, storage, receipt.manifest, MANIFEST)
    assert artifacts.content_available(receipt.raw_source.artifact_id)
    assert artifacts.content_available(receipt.manifest.artifact_id)
    assert service.reconcile(acquisition.acquisition_ref).status is PoCAcquisitionStatus.DISPATCHED
    _persist_result(database, receipt)
    completed = service.reconcile(acquisition.acquisition_ref)
    assert completed.status is PoCAcquisitionStatus.COMPLETED
    assert service.reconcile(acquisition.acquisition_ref) == completed
    with database.unit_of_work() as work:
        assert work.runs.get(invocation.run_id) is not None
        assert work.acquisitions.get_by_run(invocation.run_id) == completed


def test_foreign_node_result_cannot_complete_selected_acquisition(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, _storage, _artifacts = _components(database, tmp_path)
    _research, candidate_ref, hits, hypothesis = _seed(database)
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hits[0],
        bounds=_bounds(),
    )
    invocation = _dispatch(database, service, acquisition.acquisition_ref)
    receipt = _receipt(invocation)
    result = CapabilityResult(
        run_ref=invocation.run_id,
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.SUCCESS,
            details={"acquisition_receipt": receipt.model_dump(mode="json")},
        ),
        artifacts=(receipt.raw_source, receipt.manifest),
    )
    ingestion = ResultIngestionService(database, clock=lambda: NOW)
    ingestion.accept_result(result, source_node_id="node-foreign")
    assert ingestion.process_ingestion(invocation.run_id).status.value == "REJECTED"
    assert service.reconcile(acquisition.acquisition_ref).status is PoCAcquisitionStatus.REJECTED
