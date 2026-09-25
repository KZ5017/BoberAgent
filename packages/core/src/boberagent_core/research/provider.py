"""Replaceable, source-neutral bounded research provider boundary."""

from __future__ import annotations

from typing import Protocol

from .models import ResearchRequest, ResearchResult


class ResearchProvider(Protocol):
    provider_id: str

    async def search(self, request: ResearchRequest) -> ResearchResult: ...


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
