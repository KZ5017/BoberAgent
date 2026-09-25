"""M20-A boundary regressions: ownership, secret projection, malformed provider data."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from boberagent_contracts import (
    AssetRef,
    CapabilityRunRef,
    MissionRef,
    Observation,
    ObservationRef,
    ServiceRef,
)
from boberagent_core import Asset, CoreDatabase, CoreSecretService, ReducerRegistry
from boberagent_core.research import (
    CoreResearchService,
    DeterministicResearchProvider,
    HitDecision,
    ResearchError,
    ResearchResponseStatus,
    ResearchResult,
    ResearchStatus,
    SourceClass,
    SourceHit,
    build_research_request,
)
from conftest import NOW, add_mission_and_run


def _base(database: CoreDatabase) -> tuple[CoreResearchService, AssetRef]:
    run = add_mission_and_run(database)
    asset = Asset(
        asset_ref=AssetRef("asset-primary"),
        mission_ref=run.mission_ref,
        kind="host",
        primary_address="192.0.2.1",
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.assets.add(asset)
    return CoreResearchService(database, clock=lambda: NOW), asset.asset_ref


def test_service_on_another_asset_in_same_mission_is_rejected(database: CoreDatabase) -> None:
    research, selected_asset = _base(database)
    other_asset = Asset(
        asset_ref=AssetRef("asset-other-same-mission"),
        mission_ref=MissionRef("mission-test"),
        kind="host",
        primary_address="192.0.2.2",
        created_at=NOW,
    )
    observation = Observation(
        observation_id=ObservationRef("observation-other-same-mission"),
        type="network.service",
        subject_ref=other_asset.asset_ref,
        value={"transport": "tcp", "port": 443, "state": "open"},
        run_ref=CapabilityRunRef("run-test"),
        observed_at=NOW,
    )
    with database.unit_of_work() as work:
        work.assets.add(other_asset)
        work.observations.append(observation)
        ReducerRegistry().materialize(observation.observation_id, work)
        other_service: ServiceRef = work.services.list_for_asset(other_asset.asset_ref)[
            0
        ].service_ref
    with pytest.raises(ResearchError, match="selected Asset"):
        research.create_hypothesis(
            mission_ref=MissionRef("mission-test"),
            asset_ref=selected_asset,
            service_ref=other_service,
            claim="Another Asset's service may have a vulnerability",
            provenance="analyst",
        )


def test_canonical_secret_is_not_projected_into_research(database: CoreDatabase) -> None:
    research, asset_ref = _base(database)
    plaintext = b"synthetic-super-secret-password"
    CoreSecretService(database, clock=lambda: NOW).store(
        mission_ref=MissionRef("mission-test"),
        value=plaintext,
        secret_type="password",
    )
    hypothesis = research.create_hypothesis(
        mission_ref=MissionRef("mission-test"),
        asset_ref=asset_ref,
        claim="Example product may have CVE-2026-0001",
        vulnerability_ids=("CVE-2026-0001",),
        provenance="analyst",
    )
    request = build_research_request(
        hypothesis, allowed_source_classes=(SourceClass.REPOSITORY,), result_limit=2
    )
    assert plaintext.decode() not in request.model_dump_json()
    assert plaintext.decode() not in hypothesis.model_dump_json()


def test_rejected_tokenized_uri_is_redacted_and_not_a_candidate(database: CoreDatabase) -> None:
    research, asset_ref = _base(database)
    hypothesis = research.create_hypothesis(
        mission_ref=MissionRef("mission-test"),
        asset_ref=asset_ref,
        claim="Fixture product may have CVE-2026-0002",
        vulnerability_ids=("CVE-2026-0002",),
        provenance="analyst",
    )
    response = ResearchResult(
        status=ResearchResponseStatus.COMPLETE,
        hits=(
            SourceHit(
                source_class=SourceClass.REPOSITORY,
                source_uri="https://example.test/repo?token=synthetic-token",
                vulnerability_ids=("CVE-2026-0002",),
            ),
        ),
    )
    attempt = asyncio.run(
        research.research(
            hypothesis.hypothesis_ref,
            DeterministicResearchProvider("fixture", (response,)),
        )
    )
    assert attempt.status is ResearchStatus.NO_MATCH
    assert research.list_candidates(hypothesis.hypothesis_ref) == ()
    hit = research.list_hits(attempt.attempt_ref)[0]
    assert hit.decision is HitDecision.REJECTED
    assert "synthetic-token" not in hit.model_dump_json()


def test_over_limit_provider_response_is_safe_error(database: CoreDatabase) -> None:
    research, asset_ref = _base(database)
    hypothesis = research.create_hypothesis(
        mission_ref=MissionRef("mission-test"),
        asset_ref=asset_ref,
        claim="Fixture product may have CVE-2026-0003",
        vulnerability_ids=("CVE-2026-0003",),
        provenance="analyst",
    )
    hit = SourceHit(
        source_class=SourceClass.REPOSITORY,
        source_uri="https://example.test/repo",
        vulnerability_ids=("CVE-2026-0003",),
    )
    attempt = asyncio.run(
        research.research(
            hypothesis.hypothesis_ref,
            DeterministicResearchProvider(
                "fixture",
                (ResearchResult(status=ResearchResponseStatus.COMPLETE, hits=(hit, hit)),),
            ),
            result_limit=1,
        )
    )
    assert attempt.status is ResearchStatus.PROVIDER_ERROR
    assert research.list_candidates(hypothesis.hypothesis_ref) == ()


def test_publication_window_and_partial_diagnostic_are_bounded(database: CoreDatabase) -> None:
    research, asset_ref = _base(database)
    hypothesis = research.create_hypothesis(
        mission_ref=MissionRef("mission-test"),
        asset_ref=asset_ref,
        claim="Fixture product may have CVE-2026-0004",
        vulnerability_ids=("CVE-2026-0004",),
        provenance="analyst",
    )
    hit = SourceHit(
        source_class=SourceClass.REPOSITORY,
        source_uri="https://example.test/old",
        vulnerability_ids=("CVE-2026-0004",),
        published_at=NOW,
    )
    attempt = asyncio.run(
        research.research(
            hypothesis.hypothesis_ref,
            DeterministicResearchProvider(
                "fixture",
                (
                    ResearchResult(
                        status=ResearchResponseStatus.PARTIAL,
                        hits=(hit,),
                        diagnostic="upstream token must not be persisted",
                    ),
                ),
            ),
            published_after=NOW + timedelta(days=1),
        )
    )
    assert attempt.status is ResearchStatus.PARTIAL
    assert research.list_candidates(hypothesis.hypothesis_ref) == ()
    assert research.list_hits(attempt.attempt_ref)[0].decision is HitDecision.REJECTED
