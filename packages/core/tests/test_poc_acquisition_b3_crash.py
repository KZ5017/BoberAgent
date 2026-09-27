"""A crash after durable Result and bytes but before final transition is replayable."""

from __future__ import annotations

from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, upgrade_database
from boberagent_core.acquisitions import PoCAcquisitionStatus
from test_core_poc_acquisition import (
    MANIFEST,
    RAW,
    _bounds,
    _components,
    _dispatch,
    _persist_result,
    _publish,
    _receipt,
    _seed,
)


def test_reopen_after_result_and_both_artifacts_before_final_transition(
    database_path: Path, tmp_path: Path
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    service, storage, _artifacts = _components(database, tmp_path)
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
    _persist_result(database, receipt)
    _publish(database, storage, receipt.raw_source, RAW)
    _publish(database, storage, receipt.manifest, MANIFEST)
    pending = service.get(acquisition.acquisition_ref)
    assert pending is not None and pending.status is PoCAcquisitionStatus.DISPATCHED
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        resumed, _storage, artifacts = _components(reopened, tmp_path)
        completed = resumed.reconcile(acquisition.acquisition_ref)
        assert completed.status is PoCAcquisitionStatus.COMPLETED
        assert completed.run_ref == invocation.run_id
        assert completed.receipt == receipt
        assert artifacts.read_bytes(receipt.raw_source.artifact_id) == RAW
        assert artifacts.read_bytes(receipt.manifest.artifact_id) == MANIFEST
    finally:
        reopened.dispose()
