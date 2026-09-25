"""Offline, deterministic M20-A research smoke; no acquisition or execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from boberagent_contracts import (
    AssetRef,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    Observation,
    ObservationRef,
)
from boberagent_core import (
    Asset,
    CoreDatabase,
    DatabaseConfig,
    Mission,
    ReducerRegistry,
    upgrade_database,
)
from boberagent_core.research import (
    CoreResearchService,
    DeterministicResearchProvider,
    HitDecision,
    ResearchResponseStatus,
    ResearchResult,
    ResearchStatus,
    SourceClass,
    SourceHit,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def smoke() -> None:
    with TemporaryDirectory(prefix="boberagent-m20a-") as directory:
        database = CoreDatabase(DatabaseConfig.sqlite(Path(directory) / "core.sqlite3"))
        try:
            upgrade_database(database)
            mission = Mission(
                mission_ref=MissionRef("mission-m20a-manual"), status="ACTIVE", created_at=NOW
            )
            asset = Asset(
                asset_ref=AssetRef("asset-m20a-manual"),
                mission_ref=mission.mission_ref,
                kind="host",
                primary_address="192.0.2.40",
                created_at=NOW,
            )
            run = CapabilityRun(
                run_id=CapabilityRunRef("run-m20a-evidence"),
                capability_id="test.evidence",
                operation="observe",
                mission_ref=mission.mission_ref,
                status=CapabilityRunStatus.COMPLETED,
                created_at=NOW,
                started_at=NOW,
                finished_at=NOW,
            )
            observation = Observation(
                observation_id=ObservationRef("observation-m20a-manual"),
                type="network.service",
                subject_ref=asset.asset_ref,
                value={"transport": "tcp", "port": 8080, "state": "open", "product": "FixtureHTTP"},
                run_ref=run.run_id,
                observed_at=NOW,
            )
            with database.unit_of_work() as work:
                work.missions.add(mission)
                work.assets.add(asset)
                work.runs.add(run)
                work.observations.append(observation)
                ReducerRegistry().materialize(observation.observation_id, work)
                service_ref = work.services.list_for_asset(asset.asset_ref)[0].service_ref
            research = CoreResearchService(database, clock=lambda: NOW)
            hypothesis = research.create_hypothesis(
                mission_ref=mission.mission_ref,
                asset_ref=asset.asset_ref,
                service_ref=service_ref,
                supporting_observation_refs=(observation.observation_id,),
                claim="FixtureHTTP may be affected by CVE-2026-9999",
                vulnerability_ids=("CVE-2026-9999",),
                product="FixtureHTTP",
                provenance="offline manual fixture",
            )
            first = SourceHit(
                source_class=SourceClass.REPOSITORY,
                source_uri="https://EXAMPLE.test:443/fixture-a/",
                vulnerability_ids=("CVE-2026-9999",),
                revision_claim="rev-1",
            )
            duplicate = first.model_copy(
                update={"source_uri": "https://example.test/fixture-a", "revision_claim": "rev-2"}
            )
            second = first.model_copy(update={"source_uri": "https://example.test/fixture-b"})
            provider = DeterministicResearchProvider(
                "offline-fixture",
                (
                    ResearchResult(
                        status=ResearchResponseStatus.COMPLETE,
                        hits=(first, duplicate, second),
                    ),
                    ResearchResult(status=ResearchResponseStatus.COMPLETE),
                    RuntimeError("simulated provider outage"),
                ),
            )
            found = await research.research(hypothesis.hypothesis_ref, provider)
            no_match = await research.research(hypothesis.hypothesis_ref, provider)
            error = await research.research(hypothesis.hypothesis_ref, provider)
            candidates = research.list_candidates(hypothesis.hypothesis_ref)
            hits = research.list_hits(found.attempt_ref)
            assert len(candidates) == 2
            assert tuple(hit.decision for hit in hits) == (
                HitDecision.NEW,
                HitDecision.DUPLICATE,
                HitDecision.NEW,
            )
            assert (found.status, no_match.status, error.status) == (
                ResearchStatus.FOUND,
                ResearchStatus.NO_MATCH,
                ResearchStatus.PROVIDER_ERROR,
            )
            print(f"Mission: {mission.mission_ref}")
            print(f"Hypothesis: {hypothesis.hypothesis_ref}")
            print(f"Candidates: {', '.join(str(item.candidate_ref) for item in candidates)}")
            print("Research outcomes: FOUND, NO_MATCH, PROVIDER_ERROR")
            print("No source was downloaded or executed.")
        finally:
            database.dispose()


if __name__ == "__main__":
    asyncio.run(smoke())
