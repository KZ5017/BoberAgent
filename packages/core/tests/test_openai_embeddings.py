"""OpenAI-compatible embedding HTTP boundary without a live provider."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from boberagent_core.knowledge.openai_embeddings import (
    EmbeddingHTTPConfiguration,
    OpenAICompatibleEmbeddingProvider,
)
from boberagent_core.knowledge.semantic import (
    EmbeddingAuthenticationError,
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingResponseError,
    EmbeddingUnavailableError,
)
from pydantic import SecretStr


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = "http://localhost:1234",
    api_key: SecretStr | None = None,
) -> OpenAICompatibleEmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider(
        EmbeddingHTTPConfiguration(
            base_url=base_url, model_id="test-embedding", api_key=api_key, max_batch_size=3
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("base", ["http://localhost:1234", "http://localhost:1234/v1/"])
def test_single_and_batch_ordering_model_auth_and_endpoint(base: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer harmless-test-token"
        assert payload["model"] == "test-embedding"
        return httpx.Response(
            200,
            json={
                "model": "test-embedding",
                "data": [
                    {"index": index, "embedding": [float(index + 1), 0.5]}
                    for index in reversed(range(len(payload["input"])))
                ],
            },
        )

    provider = _provider(handler, base_url=base, api_key=SecretStr("harmless-test-token"))
    assert provider.embed(["one"]).vectors == ((1.0, 0.5),)
    assert provider.embed(["one", "two"]).vectors == ((1.0, 0.5), (2.0, 0.5))
    assert provider.embed(["one", "two"]).dimension == 2
    assert len(requests) == 3


@pytest.mark.parametrize(
    ("rows", "error"),
    [
        ([{"index": 0, "embedding": [1.0]}], EmbeddingResponseError),
        (
            [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [1.0]}],
            EmbeddingResponseError,
        ),
        (
            [{"index": 0, "embedding": []}, {"index": 1, "embedding": [1.0]}],
            EmbeddingResponseError,
        ),
        (
            [{"index": 0, "embedding": [float("nan")]}, {"index": 1, "embedding": [1.0]}],
            EmbeddingResponseError,
        ),
        (
            [{"index": 0, "embedding": [float("inf")]}, {"index": 1, "embedding": [1.0]}],
            EmbeddingResponseError,
        ),
        (
            [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [1.0, 2.0]}],
            EmbeddingDimensionError,
        ),
    ],
)
def test_invalid_rows_rejected(rows: list[dict[str, object]], error: type[Exception]) -> None:
    provider = _provider(lambda _: httpx.Response(200, json={"data": rows}))
    with pytest.raises(error):
        provider.embed(["one", "two"])


def test_bad_schema_model_and_changed_dimension_rejected() -> None:
    provider = _provider(lambda _: httpx.Response(200, json={"data": "bad"}))
    with pytest.raises(EmbeddingResponseError):
        provider.embed(["one"])

    provider = _provider(
        lambda _: httpx.Response(
            200, json={"model": "wrong", "data": [{"index": 0, "embedding": [1.0]}]}
        )
    )
    with pytest.raises(EmbeddingResponseError, match="different model"):
        provider.embed(["one"])

    count = 0

    def variable(_: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * count}]})

    provider = _provider(variable)
    provider.embed(["one"])
    with pytest.raises(EmbeddingDimensionError, match="changed"):
        provider.embed(["two"])


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, EmbeddingAuthenticationError),
        (503, EmbeddingUnavailableError),
        (400, EmbeddingConfigurationError),
    ],
)
def test_status_errors_are_typed_and_safe(status: int, expected: type[Exception]) -> None:
    def response(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="upstream-secret")

    provider = _provider(response)
    with pytest.raises(expected) as caught:
        provider.embed(["one"])
    assert "upstream-secret" not in str(caught.value)


def test_network_error_is_typed() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(EmbeddingUnavailableError):
        _provider(unavailable).embed(["one"])


def test_input_bounds_and_bad_url_fail_before_http() -> None:
    with pytest.raises(EmbeddingConfigurationError):
        _provider(lambda _: httpx.Response(200), base_url="file:///tmp/embeddings")
    provider = _provider(lambda _: httpx.Response(200))
    for values in ([], ["   "], ["a", "b", "c", "d"]):
        with pytest.raises(EmbeddingConfigurationError):
            provider.embed(values)
