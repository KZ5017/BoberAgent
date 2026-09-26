"""Mocked M20-A2 GitHub metadata search and normal Core admission."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from boberagent_contracts import AssetRef, MissionRef
from boberagent_core import Asset, CoreDatabase, DatabaseConfig, upgrade_database
from boberagent_core.research import (
    CoreResearchService,
    HitDecision,
    ResearchProviderFailure,
    ResearchProviderFailureCode,
    ResearchRequest,
    ResearchResponseStatus,
    ResearchStatus,
    SourceClass,
    VulnerabilityHypothesisRef,
)
from boberagent_core.research.providers import (
    GITHUB_SEARCH_ENDPOINT,
    QUERY_MAPPING_VERSION,
    GitHubResearchConfig,
    GitHubResearchProvider,
    github_repository_query,
)
from conftest import NOW, add_mission_and_run
from pydantic import SecretStr


def _request(*, vulnerability_ids: tuple[str, ...] = ("CVE-2026-1234",)) -> ResearchRequest:
    return ResearchRequest(
        hypothesis_ref=VulnerabilityHypothesisRef("hypothesis-github"),
        mission_ref=MissionRef("mission-github"),
        asset_ref=AssetRef("asset-github"),
        query_terms=(*vulnerability_ids, "Example Product", "Example Product issue"),
        vulnerability_ids=vulnerability_ids,
        allowed_source_classes=(SourceClass.REPOSITORY,),
        result_limit=2,
    )


def _repo(
    *,
    description: str = "CVE-2026-1234 reproduction for Example Product",
    branch: str = "main",
    url: str = "https://github.com/example/repro",
) -> dict[str, object]:
    return {
        "id": 4123,
        "name": "repro",
        "full_name": "example/repro",
        "html_url": url,
        "description": description,
        "language": "Python",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "default_branch": branch,
        "private": False,
    }


def _response(
    items: list[dict[str, object]] | None = None, *, incomplete: bool = False
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "total_count": len(items or []),
            "incomplete_results": incomplete,
            "items": items or [],
        },
    )


def _provider(
    handler: httpx.MockTransport,
    *,
    token: str | None = None,
    max_response_bytes: int = 1_048_576,
) -> GitHubResearchProvider:
    client = httpx.AsyncClient(transport=handler, follow_redirects=True, trust_env=False)
    return GitHubResearchProvider(
        GitHubResearchConfig(
            token=None if token is None else SecretStr(token),
            max_response_bytes=max_response_bytes,
        ),
        client=client,
    )


def test_versioned_query_is_deterministic_and_escaped() -> None:
    request = _request()
    assert GitHubResearchConfig().provider_id == QUERY_MAPPING_VERSION
    assert github_repository_query(request) == "CVE-2026-1234 in:name,description"
    assert github_repository_query(
        ResearchRequest.model_validate_json(request.model_dump_json())
    ) == (github_repository_query(request))
    descriptive = request.model_copy(
        update={
            "vulnerability_ids": (),
            "query_terms": ('Example Server" OR org:other', "Example Server issue"),
        }
    )
    query = github_repository_query(descriptive)
    assert query == '"Example Server org" poc in:name,description'
    assert "OR" not in query and "org:other" not in query
    with pytest.raises(ResearchProviderFailure) as failure:
        github_repository_query(
            descriptive.model_copy(update={"query_terms": ("the poc exploit",)})
        )
    assert failure.value.code is ResearchProviderFailureCode.UNSUPPORTED_QUERY
    with pytest.raises(ResearchProviderFailure):
        github_repository_query(
            request.model_copy(update={"allowed_source_classes": (SourceClass.ADVISORY,)})
        )


def test_one_fixed_bounded_search_and_metadata_normalization() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _response([_repo()])

    provider = _provider(httpx.MockTransport(handler))
    result = asyncio.run(provider.search(_request()))
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert str(calls[0].url).split("?")[0] == GITHUB_SEARCH_ENDPOINT
    assert calls[0].url.scheme == "https"
    assert parse_qs(calls[0].url.query.decode()) == {
        "q": ["CVE-2026-1234 in:name,description"],
        "per_page": ["2"],
        "page": ["1"],
    }
    assert calls[0].headers["user-agent"] == "BoberAgent-M20A2/1"
    assert result.status is ResearchResponseStatus.COMPLETE
    hit = result.hits[0]
    assert hit.source_uri == hit.repository_identity == "https://github.com/example/repro"
    assert hit.provider_result_id == "4123"
    assert hit.vulnerability_ids == ("CVE-2026-1234",)
    assert hit.revision_claim == "branch:main"
    assert hit.language_hint == "Python"
    assert hit.claimed_product is None and hit.claimed_version is None
    assert hit.published_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_incomplete_results_preserve_hits_as_partial() -> None:
    provider = _provider(httpx.MockTransport(lambda _: _response([_repo()], incomplete=True)))
    result = asyncio.run(provider.search(_request()))
    assert result.status is ResearchResponseStatus.PARTIAL
    assert len(result.hits) == 1


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(302, headers={"location": "https://example.test/elsewhere"}), "http_error"),
        (httpx.Response(401, text="token-is-secret"), "authentication"),
        (httpx.Response(403, headers={"x-ratelimit-remaining": "0"}), "rate_limited"),
        (httpx.Response(429, headers={"retry-after": "10"}), "rate_limited"),
        (httpx.Response(503, text="token-is-secret"), "unavailable"),
        (httpx.Response(200, content=b"not-json"), "invalid_response"),
        (httpx.Response(200, json={"items": []}), "invalid_response"),
        (_response([_repo(url="https://example.test/exfil")]), "invalid_response"),
        (
            _response([_repo(url="https://github.com/example/repro?token=secret")]),
            "invalid_response",
        ),
        (_response([_repo(), _repo(), _repo()]), "invalid_response"),
    ],
)
def test_bad_http_or_metadata_fails_safely_without_retry(
    response: httpx.Response, expected: str
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(ResearchProviderFailure) as error:
        asyncio.run(provider.search(_request()))
    assert error.value.code.value == expected
    assert "token-is-secret" not in str(error.value)
    assert calls == 1


def test_response_ceiling_network_and_timeout_are_safe() -> None:
    too_large = _provider(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 1200)),
        max_response_bytes=1024,
    )
    with pytest.raises(ResearchProviderFailure) as error:
        asyncio.run(too_large.search(_request()))
    assert error.value.code is ResearchProviderFailureCode.RESPONSE_TOO_LARGE

    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-in-network-error", request=request)

    def timed_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret-in-timeout-error", request=request)

    for handler, code in (
        (disconnected, ResearchProviderFailureCode.NETWORK),
        (timed_out, ResearchProviderFailureCode.TIMEOUT),
    ):
        provider = _provider(httpx.MockTransport(handler))
        with pytest.raises(ResearchProviderFailure) as failure:
            asyncio.run(provider.search(_request()))
        assert failure.value.code is code
        assert "secret-in-" not in str(failure.value)


def test_metadata_cannot_claim_vulnerability_from_search_query() -> None:
    provider = _provider(
        httpx.MockTransport(lambda _: _response([_repo(description="Unrelated example")]))
    )
    hit = asyncio.run(provider.search(_request())).hits[0]
    assert hit.vulnerability_ids == ()
    assert hit.claimed_product is None
    assert "CVE-2026-1234" not in (hit.match_excerpt or "")


def test_core_admission_dedup_history_and_token_redaction(
    database_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    run = add_mission_and_run(database)
    asset = Asset(
        asset_ref=AssetRef("asset-github"),
        mission_ref=run.mission_ref,
        kind="host",
        primary_address="192.0.2.30",
        created_at=NOW,
    )
    with database.unit_of_work() as work:
        work.assets.add(asset)
    service = CoreResearchService(database, clock=lambda: NOW)
    first = service.create_hypothesis(
        mission_ref=run.mission_ref,
        asset_ref=asset.asset_ref,
        claim="Example Product may be affected by CVE-2026-1234",
        vulnerability_ids=("CVE-2026-1234",),
        product="Example Product",
        provenance="selected test hypothesis",
    )
    second = service.create_hypothesis(
        mission_ref=run.mission_ref,
        asset_ref=asset.asset_ref,
        claim="Second hypothesis for CVE-2026-1234",
        vulnerability_ids=("CVE-2026-1234",),
        provenance="selected test hypothesis",
    )
    descriptions = [
        _repo(),
        _repo(branch="develop"),
        _repo(description="Unrelated example"),
        _repo(),
    ]
    calls = 0
    token = "harmless-github-test-token"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        assert request.headers["authorization"] == f"Bearer {token}"
        item = descriptions[calls]
        calls += 1
        return _response([item])

    provider = _provider(httpx.MockTransport(handler), token=token)
    with caplog.at_level("DEBUG"):
        first_attempt = asyncio.run(service.research(first.hypothesis_ref, provider))
        duplicate_attempt = asyncio.run(service.research(first.hypothesis_ref, provider))
        rejected_attempt = asyncio.run(service.research(first.hypothesis_ref, provider))
        other_attempt = asyncio.run(service.research(second.hypothesis_ref, provider))
    assert calls == 4
    assert [
        attempt.status
        for attempt in (first_attempt, duplicate_attempt, rejected_attempt, other_attempt)
    ] == [ResearchStatus.FOUND, ResearchStatus.FOUND, ResearchStatus.NO_MATCH, ResearchStatus.FOUND]
    first_hit = service.list_hits(first_attempt.attempt_ref)[0]
    duplicate_hit = service.list_hits(duplicate_attempt.attempt_ref)[0]
    rejected_hit = service.list_hits(rejected_attempt.attempt_ref)[0]
    assert first_hit.decision is HitDecision.NEW
    assert duplicate_hit.decision is HitDecision.DUPLICATE
    assert duplicate_hit.source.revision_claim == "branch:develop"
    assert duplicate_hit.candidate_ref == first_hit.candidate_ref
    assert rejected_hit.decision is HitDecision.REJECTED
    assert rejected_hit.candidate_ref is None
    assert service.list_hits(other_attempt.attempt_ref)[0].candidate_ref != first_hit.candidate_ref
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        after = CoreResearchService(reopened)
        assert after.get_attempt(first_attempt.attempt_ref) == first_attempt
        serialized = json.dumps(
            {
                "request": first_attempt.request.model_dump(mode="json"),
                "attempt": first_attempt.model_dump(mode="json"),
                "hit": after.list_hits(first_attempt.attempt_ref)[0].model_dump(mode="json"),
                "candidate": after.list_candidates(first.hypothesis_ref)[0].model_dump(mode="json"),
            }
        )
        assert token not in serialized
        assert token not in caplog.text
        assert token not in repr(provider._config)
    finally:
        reopened.dispose()


def test_date_bound_uses_utc_and_token_echo_is_not_persisted() -> None:
    request = _request().model_copy(
        update={
            "published_after": datetime(2026, 1, 2, 0, tzinfo=timezone(timedelta(hours=2))),
        }
    )
    assert github_repository_query(request).endswith("created:2026-01-01..*")
    token = "harmless-github-test-token"
    provider = _provider(
        httpx.MockTransport(lambda _: _response([_repo(description=f"CVE-2026-1234 {token}")])),
        token=token,
    )
    with pytest.raises(ResearchProviderFailure) as error:
        asyncio.run(provider.search(request))
    assert error.value.code is ResearchProviderFailureCode.INVALID_RESPONSE
    assert token not in str(error.value)


def test_core_records_rate_limit_as_safe_provider_error(database: CoreDatabase) -> None:
    run = add_mission_and_run(database)
    asset = Asset(
        asset_ref=AssetRef("asset-github-rate"),
        mission_ref=run.mission_ref,
        kind="host",
        primary_address="192.0.2.31",
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
    token = "harmless-github-test-token"
    provider = _provider(
        httpx.MockTransport(
            lambda _: httpx.Response(
                429, headers={"retry-after": "30"}, text=f"never persist {token}"
            )
        ),
        token=token,
    )
    attempt = asyncio.run(service.research(hypothesis.hypothesis_ref, provider))
    assert attempt.status is ResearchStatus.PROVIDER_ERROR
    assert attempt.diagnostic == "research provider rate limited"
    assert service.get_attempt(attempt.attempt_ref) == attempt
    assert service.list_hits(attempt.attempt_ref) == ()
    assert service.list_candidates(hypothesis.hypothesis_ref) == ()
    assert token not in attempt.model_dump_json()
