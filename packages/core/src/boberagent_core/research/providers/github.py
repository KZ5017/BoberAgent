"""Bounded GitHub repository *metadata* search for Core research; no content fetch."""

from __future__ import annotations

import re
from datetime import UTC
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, ValidationError

from boberagent_core.models import CoreModel

from ..models import ResearchRequest, ResearchResponseStatus, ResearchResult, SourceClass, SourceHit
from ..provider import ResearchProviderFailure, ResearchProviderFailureCode

GITHUB_SEARCH_ENDPOINT = "https://api.github.com/search/repositories"
QUERY_MAPPING_VERSION = "github-repository-search-v1"
_CVE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
_SAFE_WORD = re.compile(r"[A-Za-z][A-Za-z0-9._-]{2,}")
_REPOSITORY_PART = re.compile(r"[A-Za-z0-9_.-]+")
_STOP_WORDS = frozenset(
    {
        "affected",
        "concept",
        "exploit",
        "may",
        "proof",
        "poc",
        "test",
        "the",
        "this",
        "vulnerability",
        "with",
    }
)


class GitHubResearchConfig(CoreModel):
    """Operator-composed configuration; the token never enters a ResearchRequest."""

    provider_id: Literal["github-repository-search-v1"] = "github-repository-search-v1"
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    max_response_bytes: int = Field(default=1_048_576, ge=1024, le=8_388_608)
    user_agent: str = Field(default="BoberAgent-M20A2/1", min_length=1, max_length=128)
    token: SecretStr | None = None

    def model_post_init(self, _context: object) -> None:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", self.user_agent):
            raise ValueError("GitHub User-Agent contains unsupported characters")


class _Repository(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=3, max_length=512)
    html_url: str = Field(min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=2048)
    language: str | None = Field(default=None, max_length=64)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    default_branch: str | None = Field(default=None, max_length=200)
    private: bool


class _SearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    total_count: int = Field(ge=0)
    incomplete_results: bool
    items: list[_Repository] = Field(max_length=50)


def github_repository_query(request: ResearchRequest) -> str:
    """Mapping v1: first sorted explicit CVE, otherwise a bounded descriptive phrase.

    The provider ID is this mapping version. The persisted ResearchRequest plus provider ID
    therefore reconstruct the outbound q value without adding GitHub syntax to domain state.
    """
    if SourceClass.REPOSITORY not in request.allowed_source_classes:
        raise ResearchProviderFailure(ResearchProviderFailureCode.UNSUPPORTED_QUERY)
    identifiers = sorted(
        {value.upper() for value in request.vulnerability_ids if _CVE.fullmatch(value)}
    )
    if identifiers:
        expression = identifiers[0]
    else:
        phrase: str | None = None
        for term in request.query_terms:
            words = [
                word for word in _SAFE_WORD.findall(term) if word.casefold() not in _STOP_WORDS
            ]
            if len(words) >= 2:
                phrase = " ".join(words[:3])
                break
        if phrase is None:
            raise ResearchProviderFailure(ResearchProviderFailureCode.UNSUPPORTED_QUERY)
        expression = f'"{phrase}" poc'
    query = f"{expression} in:name,description"
    if request.published_after or request.published_before:
        after = (
            request.published_after.astimezone(UTC).date().isoformat()
            if request.published_after
            else "*"
        )
        before = (
            request.published_before.astimezone(UTC).date().isoformat()
            if request.published_before
            else "*"
        )
        query += f" created:{after}..{before}"
    if len(query) > 256:
        raise ResearchProviderFailure(ResearchProviderFailureCode.UNSUPPORTED_QUERY)
    return query


def _repository_url(repository: _Repository) -> str:
    parsed = urlsplit(repository.html_url)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 2
        or not all(_REPOSITORY_PART.fullmatch(part) for part in parts)
        or repository.full_name.casefold() != "/".join(parts).casefold()
        or repository.name.casefold() != parts[1].casefold()
        or repository.private
    ):
        raise ResearchProviderFailure(ResearchProviderFailureCode.INVALID_RESPONSE)
    return f"https://github.com/{repository.full_name}"


def _hit(repository: _Repository) -> SourceHit:
    uri = _repository_url(repository)
    description = repository.description or ""
    evidence = f"{repository.full_name} {description}".strip()
    identifiers = tuple(sorted({match.upper() for match in _CVE.findall(evidence)}))
    branch = repository.default_branch
    if branch is not None and (not branch or any(ord(character) < 32 for character in branch)):
        raise ResearchProviderFailure(ResearchProviderFailureCode.INVALID_RESPONSE)
    return SourceHit(
        source_class=SourceClass.REPOSITORY,
        source_uri=uri,
        repository_identity=uri,
        title=repository.full_name,
        summary=repository.description,
        match_excerpt=evidence[:1024],
        vulnerability_ids=identifiers[:16],
        revision_claim=None if branch is None else f"branch:{branch}",
        language_hint=repository.language,
        published_at=repository.created_at,
        updated_at=repository.updated_at,
        provider_result_id=str(repository.id),
    )


class GitHubResearchProvider:
    """One fixed-endpoint, first-page repository search; no follow-up requests."""

    def __init__(
        self, config: GitHubResearchConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self.provider_id: str = config.provider_id
        self._config = config
        self._client = client or httpx.AsyncClient(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> GitHubResearchProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def search(self, request: ResearchRequest) -> ResearchResult:
        query = github_repository_query(request)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": self._config.user_agent,
        }
        if self._config.token is not None:
            headers["Authorization"] = f"Bearer {self._config.token.get_secret_value()}"
        content = bytearray()
        try:
            async with self._client.stream(
                "GET",
                GITHUB_SEARCH_ENDPOINT,
                params={"q": query, "per_page": request.result_limit, "page": 1},
                headers=headers,
                timeout=self._config.timeout_seconds,
                follow_redirects=False,
            ) as response:
                status = response.status_code
                if status == 401:
                    raise ResearchProviderFailure(ResearchProviderFailureCode.AUTHENTICATION)
                if status == 429 or (
                    status == 403
                    and (
                        response.headers.get("x-ratelimit-remaining") == "0"
                        or "retry-after" in response.headers
                    )
                ):
                    raise ResearchProviderFailure(ResearchProviderFailureCode.RATE_LIMITED)
                if status == 422:
                    raise ResearchProviderFailure(ResearchProviderFailureCode.UNSUPPORTED_QUERY)
                if status >= 500:
                    raise ResearchProviderFailure(ResearchProviderFailureCode.UNAVAILABLE)
                if status != 200:
                    raise ResearchProviderFailure(
                        ResearchProviderFailureCode.AUTHENTICATION
                        if status == 403
                        else ResearchProviderFailureCode.HTTP_ERROR
                    )
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self._config.max_response_bytes:
                        raise ResearchProviderFailure(
                            ResearchProviderFailureCode.RESPONSE_TOO_LARGE
                        )
        except httpx.TimeoutException:
            raise ResearchProviderFailure(ResearchProviderFailureCode.TIMEOUT) from None
        except httpx.RequestError:
            raise ResearchProviderFailure(ResearchProviderFailureCode.NETWORK) from None

        try:
            payload = _SearchResponse.model_validate_json(bytes(content))
            if len(payload.items) > request.result_limit:
                raise ValueError("GitHub returned more repositories than requested")
            hits = tuple(_hit(item) for item in payload.items)
            token = (
                self._config.token.get_secret_value() if self._config.token is not None else None
            )
            if token and any(token in hit.model_dump_json() for hit in hits):
                raise ResearchProviderFailure(ResearchProviderFailureCode.INVALID_RESPONSE)
        except (ValidationError, ValueError):
            raise ResearchProviderFailure(ResearchProviderFailureCode.INVALID_RESPONSE) from None
        return ResearchResult(
            status=(
                ResearchResponseStatus.PARTIAL
                if payload.incomplete_results
                else ResearchResponseStatus.COMPLETE
            ),
            hits=hits,
        )
