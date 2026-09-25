"""M20-A: bounded research leads, not target facts or executable content."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from boberagent_contracts import (
    ArtifactRef,
    AssetRef,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    Observation,
    ObservationRef,
    ServiceRef,
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
    ResearchError,
    ResearchResponseStatus,
    ResearchResult,
    ResearchStatus,
    SourceClass,
    SourceHit,
    VulnerabilityHypothesis,
    VulnerabilityHypothesisRef,
    build_research_request,
)
from conftest import NOW, add_mission_and_run


def _seed(database: CoreDatabase) -> tuple[AssetRef, ServiceRef, ObservationRef]:
    run = add_mission_and_run(database)
    asset = Asset(
        asset_ref=AssetRef("asset-research"),
        mission_ref=run.mission_ref,
        kind="host",
        primary_address="192.0.2.10",
        created_at=NOW,
    )
    observation = Observation(
        observation_id=ObservationRef("observation-research"),
        type="network.service",
        subject_ref=asset.asset_ref,
        value={"transport": "tcp", "port": 80, "state": "open", "service": "http"},
        run_ref=run.run_id,
        observed_at=NOW,
    )
    with database.unit_of_work() as work:
        work.assets.add(asset)
        work.observations.append(observation)
        service = ReducerRegistry().materialize(observation.observation_id, work)
        assert service.value == "MATERIALIZED"
        service_ref = work.services.list_for_asset(asset.asset_ref)[0].service_ref
    return asset.asset_ref, service_ref, observation.observation_id


def _other(database: CoreDatabase) -> tuple[AssetRef, ServiceRef, ObservationRef]:
    mission = Mission(mission_ref=MissionRef("mission-other"), status="ACTIVE", created_at=NOW)
    run = CapabilityRun(
        run_id=CapabilityRunRef("run-other"),
        capability_id="test.source",
        operation="read",
        mission_ref=mission.mission_ref,
        status=CapabilityRunStatus.COMPLETED,
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW,
    )
    asset = Asset(
        asset_ref=AssetRef("asset-other"),
        mission_ref=mission.mission_ref,
        kind="host",
        primary_address="198.51.100.20",
        created_at=NOW,
    )
    observation = Observation(
        observation_id=ObservationRef("observation-other"),
        type="network.service",
        subject_ref=asset.asset_ref,
        value={"transport": "tcp", "port": 443, "state": "open"},
        run_ref=run.run_id,
        observed_at=NOW,
    )
    with database.unit_of_work() as work:
        work.missions.add(mission)
        work.runs.add(run)
        work.assets.add(asset)
        work.observations.append(observation)
        ReducerRegistry().materialize(observation.observation_id, work)
        service_ref = work.services.list_for_asset(asset.asset_ref)[0].service_ref
    return asset.asset_ref, service_ref, observation.observation_id


def _hypothesis(
    service: CoreResearchService,
    asset: AssetRef,
    *,
    service_ref: ServiceRef | None = None,
    supporting_observation_refs: tuple[ObservationRef, ...] = (),
) -> VulnerabilityHypothesis:
    return service.create_hypothesis(
        mission_ref=MissionRef("mission-test"),
        asset_ref=asset,
        claim="Example Server may be affected by CVE-2026-1234",
        provenance="analyst-selected assessment lead",
        vulnerability_ids=("CVE-2026-1234",),
        product="Example Server",
        version="1.0",
        service_ref=service_ref,
        supporting_observation_refs=supporting_observation_refs,
    )


def _hit(uri: str, *, revision: str = "rev-a", product: str = "Example Server") -> SourceHit:
    return SourceHit(
        source_class=SourceClass.REPOSITORY,
        source_uri=uri,
        repository_identity=uri,
        title="Example reproduction",
        match_excerpt="CVE-2026-1234 affects Example Server",
        vulnerability_ids=("CVE-2026-1234",),
        claimed_product=product,
        claimed_version="1.0",
        revision_claim=revision,
        provider_result_id=f"result-{revision}",
    )


def test_hypothesis_ownership_and_no_world_state_mutation(database: CoreDatabase) -> None:
    asset, service_ref, observation_ref = _seed(database)
    other_asset, other_service, other_observation = _other(database)
    research = CoreResearchService(database, clock=lambda: NOW)
    hypothesis = _hypothesis(
        research, asset, service_ref=service_ref, supporting_observation_refs=(observation_ref,)
    )
    assert research.get_hypothesis(hypothesis.hypothesis_ref) == hypothesis
    assert research.list_hypotheses(hypothesis.mission_ref) == (hypothesis,)
    with database.unit_of_work() as work:
        assert work.services.get(service_ref) is not None
        assert work.observations.get(observation_ref) is not None
        assert work.goals.list_for_mission(hypothesis.mission_ref) == ()

    for wrong_asset in (AssetRef("asset-missing"), other_asset):
        with pytest.raises(ResearchError):
            _hypothesis(research, wrong_asset)
    for wrong_service in (other_service, ServiceRef("service-missing")):
        with pytest.raises(ResearchError):
            _hypothesis(research, asset, service_ref=wrong_service)
    for wrong_observation in (other_observation, ObservationRef("observation-missing")):
        with pytest.raises(ResearchError):
            _hypothesis(research, asset, supporting_observation_refs=(wrong_observation,))
    with pytest.raises(ResearchError):
        research.create_hypothesis(
            mission_ref=MissionRef("mission-missing"),
            asset_ref=asset,
            claim="A sufficiently bounded claim",
            provenance="analyst",
        )


def test_request_contains_only_bounded_hypothesis_fields(database: CoreDatabase) -> None:
    asset, _, _ = _seed(database)
    research = CoreResearchService(database, clock=lambda: NOW)
    hypothesis = _hypothesis(research, asset)
    request = build_research_request(
        hypothesis, allowed_source_classes=(SourceClass.REPOSITORY,), result_limit=3
    )
    assert request.query_terms == (
        "CVE-2026-1234",
        "Example Server",
        "1.0",
        hypothesis.claim,
    )
    encoded = request.model_dump_json()
    assert "asset-research" in encoded
    assert "192.0.2.10" not in encoded
    assert "password" not in encoded.lower()
    with pytest.raises(ValueError):
        build_research_request(
            hypothesis, allowed_source_classes=(SourceClass.REPOSITORY,), result_limit=51
        )


def test_candidate_dedupe_revisions_and_reopen(database_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    asset, _, _ = _seed(database)
    research = CoreResearchService(database, clock=lambda: NOW)
    hypothesis = _hypothesis(research, asset)
    first = _hit("https://EXAMPLE.test:443/repo/")
    alias = _hit("https://example.test/repo", revision="rev-b")
    distinct = _hit("https://example.test/another")
    provider = DeterministicResearchProvider(
        "fixture-research",
        (
            ResearchResult(status=ResearchResponseStatus.COMPLETE, hits=(first, alias, distinct)),
            ResearchResult(status=ResearchResponseStatus.COMPLETE, hits=(alias,)),
        ),
    )
    attempt = asyncio.run(research.research(hypothesis.hypothesis_ref, provider, result_limit=3))
    assert attempt.status is ResearchStatus.FOUND
    assert len(provider.requests) == 1
    hits = research.list_hits(attempt.attempt_ref)
    assert tuple(hit.decision for hit in hits) == (
        HitDecision.NEW,
        HitDecision.DUPLICATE,
        HitDecision.NEW,
    )
    assert [hit.source.revision_claim for hit in hits] == ["rev-a", "rev-b", "rev-a"]
    assert hits[0].candidate_ref == hits[1].candidate_ref
    candidates = research.list_candidates(hypothesis.hypothesis_ref)
    assert len(candidates) == 2
    assert candidates[0].candidate_ref != candidates[1].candidate_ref
    second = asyncio.run(research.research(hypothesis.hypothesis_ref, provider))
    assert research.list_hits(second.attempt_ref)[0].decision is HitDecision.DUPLICATE
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        after_restart = CoreResearchService(reopened)
        assert len(after_restart.list_attempts(hypothesis.hypothesis_ref)) == 2
        assert after_restart.get_candidate(candidates[0].candidate_ref) == candidates[0]
        assert [
            hit.source.revision_claim for hit in after_restart.list_hits(attempt.attempt_ref)
        ] == ["rev-a", "rev-b", "rev-a"]
    finally:
        reopened.dispose()


def test_no_match_partial_error_and_rejected_hit(database: CoreDatabase) -> None:
    asset, _, _ = _seed(database)
    research = CoreResearchService(database, clock=lambda: NOW)
    hypothesis = _hypothesis(research, asset)
    bad = _hit("https://example.test/repo?token=not-allowed")
    unrelated = SourceHit(
        source_class=SourceClass.REPOSITORY,
        source_uri="https://example.test/unrelated",
        match_excerpt="Different technology",
        claimed_product="Unrelated",
    )
    provider = DeterministicResearchProvider(
        "fixture-research",
        (
            ResearchResult(status=ResearchResponseStatus.COMPLETE),
            ResearchResult(status=ResearchResponseStatus.PARTIAL, hits=(bad, unrelated)),
            RuntimeError("upstream token must not enter diagnostics"),
        ),
    )
    no_match = asyncio.run(research.research(hypothesis.hypothesis_ref, provider))
    partial = asyncio.run(research.research(hypothesis.hypothesis_ref, provider))
    error = asyncio.run(research.research(hypothesis.hypothesis_ref, provider))
    assert [item.status for item in (no_match, partial, error)] == [
        ResearchStatus.NO_MATCH,
        ResearchStatus.PARTIAL,
        ResearchStatus.PROVIDER_ERROR,
    ]
    assert len(research.list_candidates(hypothesis.hypothesis_ref)) == 0
    assert [hit.decision for hit in research.list_hits(partial.attempt_ref)] == [
        HitDecision.REJECTED,
        HitDecision.REJECTED,
    ]
    assert "token" not in (error.diagnostic or "")
    assert len(research.list_attempts(hypothesis.hypothesis_ref)) == 3


def test_same_source_is_distinct_per_hypothesis_and_no_execution(
    database: CoreDatabase,
) -> None:
    asset, _, _ = _seed(database)
    research = CoreResearchService(database, clock=lambda: NOW)
    first = _hypothesis(research, asset)
    second = _hypothesis(research, asset)
    for hypothesis in (first, second):
        provider = DeterministicResearchProvider(
            "fixture-research",
            (
                ResearchResult(
                    status=ResearchResponseStatus.COMPLETE,
                    hits=(_hit("https://example.test/repo"),),
                ),
            ),
        )
        asyncio.run(research.research(hypothesis.hypothesis_ref, provider))
    assert (
        research.list_candidates(first.hypothesis_ref)[0].candidate_ref
        != research.list_candidates(second.hypothesis_ref)[0].candidate_ref
    )
    with database.unit_of_work() as work:
        assert work.runs.get(CapabilityRunRef("run-test")) is not None
        assert work.runs.get(CapabilityRunRef("run-research")) is None
        assert work.artifacts.get_record(ArtifactRef("artifact-research")) is None
    research.retire_hypothesis(first.hypothesis_ref)
    with pytest.raises(ResearchError):
        asyncio.run(
            research.research(first.hypothesis_ref, DeterministicResearchProvider("fixture", ()))
        )


def test_typed_reference_rejects_other_ref_type() -> None:
    with pytest.raises(ValueError):
        VulnerabilityHypothesisRef("not a valid ref")
