"""No live model: Chat Completions adapter is exercised through HTTP mock transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from boberagent_contracts import AssetRef, MissionRef
from boberagent_core import GoalRef, GoalStatus
from boberagent_core.reasoning import (
    EvidenceStrength,
    InterpretationResult,
    OpenAICompatibleReasonerProvider,
    ReasonerAuthenticationError,
    ReasonerConfigurationError,
    ReasonerGeneration,
    ReasonerHTTPConfiguration,
    ReasonerIncompleteError,
    ReasonerOutputValidationError,
    ReasonerResponseError,
    ReasonerUnavailableError,
    StructuredReasoning,
)
from boberagent_core.reasoning.models import (
    AssetContext,
    ContextBudget,
    GoalContext,
    ReasoningContext,
)
from pydantic import SecretStr


def _context() -> ReasoningContext:
    return ReasoningContext(
        mission_ref=MissionRef("mission-reasoner-http"),
        goal=GoalContext(
            goal_ref=GoalRef("goal-reasoner-http"),
            goal_type="service_discovery",
            status=GoalStatus.ACTIVE,
        ),
        asset=AssetContext(
            asset_ref=AssetRef("asset-reasoner-http"),
            kind="host",
            primary_address="192.0.2.1",
        ),
        services=(),
        observation_refs=(),
        procedure=None,
        attempts=(),
        knowledge=(),
        capabilities=(),
        diagnostic_codes=(),
        budget=ContextBudget(
            max_chars=2000, included_chars=300, included_counts={}, omitted_counts={}
        ),
    )


def _body(*, content: str | None = None, finish_reason: str = "stop") -> dict[str, object]:
    valid = StructuredReasoning(
        interpretation=InterpretationResult(
            summary="Service identity remains uncertain.",
            evidence_strength=EvidenceStrength.MIXED,
        )
    )
    return {
        "model": "reasoner-test",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": valid.model_dump_json() if content is None else content,
                },
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10},
    }


def _request(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = "http://reasoner.local:1234",
    api_key: SecretStr | None = None,
) -> ReasonerGeneration[StructuredReasoning]:
    async def execute() -> ReasonerGeneration[StructuredReasoning]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleReasonerProvider(
                ReasonerHTTPConfiguration(
                    base_url=base_url,
                    model_id="reasoner-test",
                    api_key=api_key,
                    timeout_seconds=7,
                    temperature=0,
                    max_output_tokens=512,
                ),
                client=client,
            )
            return await provider.generate(_context(), StructuredReasoning)

    return asyncio.run(execute())


@pytest.mark.parametrize(
    "base_url", ["http://reasoner.local:1234", "http://reasoner.local:1234/v1/"]
)
def test_structured_request_auth_model_schema_settings_and_usage(base_url: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer harmless-test-token"
        assert body["model"] == "reasoner-test"
        assert body["temperature"] == 0
        assert body["max_tokens"] == 512
        assert body["stream"] is False
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["schema"]["type"] == "object"
        assert (
            "inputs"
            in body["response_format"]["json_schema"]["schema"]["$defs"]["ActionProposal"][
                "required"
            ]
        )
        assert "inputs satisfying" in body["messages"][0]["content"]
        assert "proposal=null" in body["messages"][0]["content"]
        assert len(body["messages"]) == 2
        assert body["messages"][1]["role"] == "user"
        assert "mission-reasoner-http" in body["messages"][1]["content"]
        assert "harmless-test-token" not in request.content.decode()
        return httpx.Response(200, json=_body())

    generation = _request(handler, base_url=base_url, api_key=SecretStr("harmless-test-token"))
    assert len(seen) == 1
    assert generation.value.interpretation.evidence_strength is EvidenceStrength.MIXED
    assert generation.provider_id == "openai-compatible-chat"
    assert generation.model_id == "reasoner-test"
    assert generation.usage is not None
    assert generation.usage.prompt_tokens == 20


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({}, ReasonerResponseError),
        ({"choices": []}, ReasonerResponseError),
        ({"choices": [{"finish_reason": "stop"}]}, ReasonerResponseError),
        (
            {"choices": [{"finish_reason": "stop", "message": {"role": "assistant"}}]},
            ReasonerResponseError,
        ),
        (
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": ""}}
                ]
            },
            ReasonerResponseError,
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "{}", "tool_calls": [{}]},
                    }
                ]
            },
            ReasonerResponseError,
        ),
        ({"model": "wrong", "choices": _body()["choices"]}, ReasonerResponseError),
        (_body(content="not-json"), ReasonerResponseError),
        (_body(content='{"interpretation": {"summary": "x"}}'), ReasonerOutputValidationError),
        (_body(finish_reason="length"), ReasonerIncompleteError),
    ],
)
def test_invalid_response_shapes_are_rejected_safely(
    payload: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        _request(lambda _: httpx.Response(200, json=payload))


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ReasonerAuthenticationError),
        (503, ReasonerUnavailableError),
        (400, ReasonerConfigurationError),
    ],
)
def test_http_failures_do_not_echo_upstream_body(status: int, error: type[Exception]) -> None:
    with pytest.raises(error) as caught:
        _request(lambda _: httpx.Response(status, text="upstream-private-value"))
    assert "upstream-private-value" not in str(caught.value)


def test_network_error_and_base_url_validation() -> None:
    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ReasonerUnavailableError):
        _request(disconnected)
    with pytest.raises(ReasonerConfigurationError):
        OpenAICompatibleReasonerProvider(
            ReasonerHTTPConfiguration(
                base_url="https://user:password@host/v1", model_id="reasoner-test"
            )
        )
