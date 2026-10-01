"""B3 forward migration preserves B1 GitHub acquisition rows."""

from __future__ import annotations

import json
from pathlib import Path

from boberagent_contracts import PoCAcquisitionRef
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    current_revision,
    upgrade_database,
)
from boberagent_core.acquisitions import CorePoCAcquisitionService
from sqlalchemy import text
from test_core_poc_acquisition import NOW, _bounds, _seed


def test_upgrade_from_b1_keeps_acquisition_identity_and_defaults_to_github(
    database_path: Path, tmp_path: Path
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database, "0010_m20_acquisition")
        _research, candidate_ref, hits, hypothesis = _seed(database)
        with database.unit_of_work() as work:
            hit = work.research.get_hit(hits[0])
            assert hit is not None
        acquisition_ref = PoCAcquisitionRef("poc-acquisition-before-b3")
        with database._migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO poc_acquisitions (acquisition_id, mission_id, hypothesis_id, "
                    "candidate_id, selected_hit_id, research_attempt_id, research_provider_id, "
                    "source_identity, source_uri, repository_uri, provider_repository_id, "
                    "historical_ref, bounds_json, status, created_at, updated_at) VALUES "
                    "(:acquisition, :mission, :hypothesis, :candidate, :hit, :attempt, :provider, "
                    ":identity, :uri, :repository, :repository_id, :ref, :bounds, 'REQUESTED', "
                    ":created, :updated)"
                ),
                {
                    "acquisition": str(acquisition_ref),
                    "mission": str(hypothesis.mission_ref),
                    "hypothesis": str(hypothesis.hypothesis_ref),
                    "candidate": str(candidate_ref),
                    "hit": hits[0],
                    "attempt": str(hit.attempt_ref),
                    "provider": hit.provider_id,
                    "identity": hit.source_identity,
                    "uri": hit.source.source_uri,
                    "repository": hit.source.repository_identity,
                    "repository_id": 42,
                    "ref": hit.source.revision_claim,
                    "bounds": json.dumps(_bounds().model_dump(mode="json")),
                    "created": NOW.isoformat(),
                    "updated": NOW.isoformat(),
                },
            )
        upgrade_database(database)
        assert current_revision(database) == "0016_m20_e2_preparation"
        storage = FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "store"))
        service = CorePoCAcquisitionService(database, CoreArtifactService(database, storage))
        restored = service.get(acquisition_ref)
        assert restored is not None
        assert restored.selected_hit_id == hits[0]
        assert restored.source_kind == "github_repository"
        assert restored.fixture_port is None
    finally:
        database.dispose()
