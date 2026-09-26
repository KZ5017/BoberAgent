"""M20-A2 conservative recovery of abandoned persisted research attempts."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from boberagent_contracts import AssetRef
from boberagent_core import Asset, CoreDatabase, DatabaseConfig, upgrade_database
from boberagent_core.research import (
    CoreResearchService,
    ResearchAttempt,
    ResearchAttemptRef,
    ResearchError,
    ResearchStatus,
    SourceClass,
    build_research_request,
)
from boberagent_core.research.service import DEFAULT_RECOVERY_GRACE, MAX_RESEARCH_TIMEOUT
from conftest import NOW, add_mission_and_run


def _setup(database: CoreDatabase) -> tuple[CoreResearchService, ResearchAttempt]:
    run = add_mission_and_run(database)
    asset = Asset(
        asset_ref=AssetRef("asset-recovery"),
        mission_ref=run.mission_ref,
        kind="host",
        primary_address="192.0.2.44",
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.assets.add(asset)
    service = CoreResearchService(database, clock=lambda: NOW)
    hypothesis = service.create_hypothesis(
        mission_ref=run.mission_ref,
        asset_ref=asset.asset_ref,
        claim="Example Product may be affected by CVE-2026-1234",
        vulnerability_ids=("CVE-2026-1234",),
        provenance="test",
    )
    request = build_research_request(
        hypothesis, allowed_source_classes=(SourceClass.REPOSITORY,), result_limit=2
    )
    attempt = ResearchAttempt(
        attempt_ref=ResearchAttemptRef("research-attempt-stale"),
        hypothesis_ref=hypothesis.hypothesis_ref,
        provider_id="github-repository-search-v1",
        request=request,
        status=ResearchStatus.STARTED,
        started_at=NOW,
    )
    return service, attempt


def test_recovery_after_reopen_is_bounded_idempotent_and_does_not_retry(
    database_path: Path,
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    _, stale = _setup(database)
    boundary = NOW + MAX_RESEARCH_TIMEOUT + DEFAULT_RECOVERY_GRACE
    fresh = stale.model_copy(
        update={
            "attempt_ref": ResearchAttemptRef("research-attempt-fresh"),
            "started_at": NOW + timedelta(seconds=1),
        }
    )
    terminal = stale.model_copy(
        update={
            "attempt_ref": ResearchAttemptRef("research-attempt-terminal"),
            "status": ResearchStatus.NO_MATCH,
            "finished_at": NOW + timedelta(seconds=5),
        }
    )
    with database.unit_of_work() as work:
        work.research.add_attempt(stale)
        work.research.add_attempt(fresh)
        work.research.add_attempt(terminal)
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        service = CoreResearchService(reopened, clock=lambda: boundary - timedelta(microseconds=1))
        assert service.reconcile_abandoned_attempts() == 0
        service = CoreResearchService(reopened, clock=lambda: boundary)
        assert service.reconcile_abandoned_attempts() == 1
        assert service.reconcile_abandoned_attempts() == 0
        interrupted = service.get_attempt(stale.attempt_ref)
        assert interrupted is not None
        assert interrupted.status is ResearchStatus.INTERRUPTED
        assert interrupted.finished_at == boundary
        assert interrupted.request == stale.request
        assert interrupted.diagnostic == (
            "Core research attempt interrupted before a result was recorded"
        )
        assert service.get_attempt(fresh.attempt_ref) == fresh
        assert service.get_attempt(terminal.attempt_ref) == terminal
        assert service.list_hits(stale.attempt_ref) == ()
        assert service.list_candidates(stale.hypothesis_ref) == ()
        with pytest.raises(ResearchError):
            service.reconcile_abandoned_attempts(grace=timedelta(0))
    finally:
        reopened.dispose()
