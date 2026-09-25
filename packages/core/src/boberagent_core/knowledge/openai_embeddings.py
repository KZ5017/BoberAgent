"""OpenAI-compatible embeddings only; no chat or LM Studio-native API."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr

from boberagent_core.models import CoreModel

from .semantic import (
    EmbeddingAuthenticationError,
    EmbeddingBatch,
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingResponseError,
    EmbeddingUnavailableError,
)


class EmbeddingHTTPConfiguration(CoreModel):
    base_url: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_batch_size: int = Field(default=16, ge=1, le=256)


class OpenAICompatibleEmbeddingProvider:
    """Ordered, validated `POST /v1/embeddings` adapter."""

    provider_id = "openai-compatible"

    def __init__(
        self, config: EmbeddingHTTPConfiguration, *, client: httpx.Client | None = None
    ) -> None:
        parsed = urlsplit(config.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise EmbeddingConfigurationError("embedding base URL must be an HTTP(S) URL")
        path = parsed.path.rstrip("/")
        if path.endswith("/embeddings"):
            raise EmbeddingConfigurationError("base URL must not include the embeddings endpoint")
        if not path.endswith("/v1"):
            path += "/v1"
        self._endpoint = parsed._replace(path=f"{path}/embeddings").geturl()
        self._config = config
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self._owns_client = client is None
        self._dimension: int | None = None

    @property
    def model_id(self) -> str:
        return self._config.model_id

    @property
    def max_batch_size(self) -> int:
        return self._config.max_batch_size

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAICompatibleEmbeddingProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts or len(texts) > self.max_batch_size or any(not text.strip() for text in texts):
            raise EmbeddingConfigurationError("embedding batch must contain bounded nonblank texts")
        headers: dict[str, str] = {}
        if self._config.api_key is not None:
            headers["Authorization"] = f"Bearer {self._config.api_key.get_secret_value()}"
        try:
            response = self._client.post(
                self._endpoint,
                json={"model": self.model_id, "input": list(texts)},
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                raise EmbeddingAuthenticationError(
                    "embedding provider rejected authentication"
                ) from error
            if status == 429 or status >= 500:
                raise EmbeddingUnavailableError(
                    f"embedding provider returned HTTP {status}"
                ) from error
            raise EmbeddingConfigurationError(
                f"embedding provider rejected request: HTTP {status}"
            ) from error
        except httpx.RequestError as error:
            raise EmbeddingUnavailableError("embedding provider is unavailable") from error
        except ValueError as error:
            raise EmbeddingResponseError("embedding provider returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise EmbeddingResponseError("embedding provider returned an invalid object")
        returned_model = payload.get("model")
        if returned_model is not None and returned_model != self.model_id:
            raise EmbeddingResponseError("embedding provider returned a different model")
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise EmbeddingResponseError("embedding provider returned the wrong number of rows")
        by_index: dict[int, tuple[float, ...]] = {}
        for row in rows:
            if not isinstance(row, dict) or type(row.get("index")) is not int:
                raise EmbeddingResponseError("embedding provider returned an invalid row index")
            index = row["index"]
            raw = row.get("embedding")
            if index in by_index or index < 0 or index >= len(texts):
                raise EmbeddingResponseError(
                    "embedding provider returned duplicate or invalid indexes"
                )
            if not isinstance(raw, list) or not raw:
                raise EmbeddingResponseError("embedding provider returned an empty vector")
            if any(type(value) not in {int, float} or not isfinite(value) for value in raw):
                raise EmbeddingResponseError("embedding provider returned a non-finite vector")
            by_index[index] = tuple(float(value) for value in raw)
        if set(by_index) != set(range(len(texts))):
            raise EmbeddingResponseError("embedding provider omitted one or more indexes")
        vectors = tuple(by_index[index] for index in range(len(texts)))
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise EmbeddingDimensionError("embedding provider returned inconsistent dimensions")
        dimension = dimensions.pop()
        if self._dimension is not None and dimension != self._dimension:
            raise EmbeddingDimensionError("embedding provider changed vector dimension")
        self._dimension = dimension
        return EmbeddingBatch(
            provider_id=self.provider_id,
            model_id=self.model_id,
            vectors=vectors,
            dimension=dimension,
        )
