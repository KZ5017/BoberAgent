"""Replaceable, source-neutral bounded research provider boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from .models import ResearchRequest, ResearchResult


class ResearchProvider(Protocol):
    provider_id: str

    async def search(self, request: ResearchRequest) -> ResearchResult: ...


class ResearchProviderFailureCode(StrEnum):
    """Safe operational categories; no upstream response text is carried."""

    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_RESPONSE = "invalid_response"
    UNSUPPORTED_QUERY = "unsupported_query"
    HTTP_ERROR = "http_error"
    UNAVAILABLE = "unavailable"


class ResearchProviderFailure(Exception):
    """A provider failure with a bounded, token-free diagnostic."""

    def __init__(self, code: ResearchProviderFailureCode) -> None:
        self.code = code
        super().__init__(f"research provider {code.value.replace('_', ' ')}")


class DeterministicResearchProvider:
    """Injected response sequence for deterministic tests and manual validation only."""

    def __init__(self, provider_id: str, responses: tuple[ResearchResult | Exception, ...]) -> None:
        self.provider_id = provider_id
        self._responses = iter(responses)
        self.requests: list[ResearchRequest] = []

    async def search(self, request: ResearchRequest) -> ResearchResult:
        self.requests.append(request)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response
