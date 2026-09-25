"""Provider-independent structured generation and a bounded Chat Completions adapter."""

from __future__ import annotations

import json
from typing import Protocol, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, ValidationError

from boberagent_core.models import CoreModel

from .models import ReasonerGeneration, ReasonerUsage, ReasoningContext

T = TypeVar("T", bound=CoreModel)


class ReasonerError(RuntimeError):
    """Safe provider boundary error; never includes raw upstream response bodies."""


class ReasonerConfigurationError(ReasonerError):
    pass


class ReasonerAuthenticationError(ReasonerError):
    pass


class ReasonerUnavailableError(ReasonerError):
    pass


class ReasonerResponseError(ReasonerError):
    pass


class ReasonerOutputValidationError(ReasonerResponseError):
    pass


class ReasonerIncompleteError(ReasonerResponseError):
    pass


class ReasonerProvider(Protocol):
    """Replaceable structured-output generation; no tools or execution methods."""

    async def generate(
        self, context: ReasoningContext, output_type: type[T]
    ) -> ReasonerGeneration[T]: ...


class ReasonerHTTPConfiguration(CoreModel):
    base_url: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=2048, ge=128, le=16384)


_SYSTEM_INSTRUCTION = (
    "BoberAgent bounded interpretation v2. Interpret only the supplied structured context. "
    "World State evidence outranks assumptions; active Procedures outrank semantic suggestions; "
    "canonical Knowledge outranks model memory. Cite supplied logical refs only. "
    "Unknown or conflicting evidence remains uncertain. Return only the requested JSON schema. "
    "If proposing an action, explicitly provide inputs satisfying that selected capability "
    "operation's supplied input_schema. Proposal-level refs do not replace operation inputs. "
    "Do not invent required inputs absent from context; return proposal=null and identify missing "
    "information if those inputs cannot be derived. "
    "Do not request tools, invent verification, output secret material, or claim to execute actions."
)


class OpenAICompatibleReasonerProvider:
    """Single-choice `POST /v1/chat/completions` with constrained JSON schema output."""

    provider_id = "openai-compatible-chat"

    def __init__(
        self, config: ReasonerHTTPConfiguration, *, client: httpx.AsyncClient | None = None
    ) -> None:
        parsed = urlsplit(config.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ReasonerConfigurationError("reasoner base URL must be an HTTP(S) URL")
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            raise ReasonerConfigurationError("base URL must not include the chat endpoint")
        if not path.endswith("/v1"):
            path += "/v1"
        self._endpoint = parsed._replace(path=f"{path}/chat/completions").geturl()
        self._config = config
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OpenAICompatibleReasonerProvider:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def generate(
        self, context: ReasoningContext, output_type: type[T]
    ) -> ReasonerGeneration[T]:
        headers: dict[str, str] = {}
        if self._config.api_key is not None:
            headers["Authorization"] = f"Bearer {self._config.api_key.get_secret_value()}"
        request = {
            "model": self._config.model_id,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_output_tokens,
            "n": 1,
            "stream": False,
            "messages": [
                {"role": "system", "content": _SYSTEM_INSTRUCTION},
                {"role": "user", "content": context.model_dump_json()},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_type.__name__,
                    "strict": True,
                    "schema": output_type.model_json_schema(),
                },
            },
        }
        try:
            response = await self._client.post(
                self._endpoint,
                json=request,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                raise ReasonerAuthenticationError("reasoner authentication was rejected") from None
            if status == 429 or status >= 500:
                raise ReasonerUnavailableError(f"reasoner returned HTTP {status}") from None
            raise ReasonerConfigurationError(
                f"reasoner request was rejected: HTTP {status}"
            ) from None
        except httpx.RequestError:
            raise ReasonerUnavailableError("reasoner provider is unavailable") from None
        except ValueError:
            raise ReasonerResponseError("reasoner returned invalid JSON") from None

        if not isinstance(payload, dict):
            raise ReasonerResponseError("reasoner returned an invalid response object")
        returned_model = payload.get("model")
        if returned_model is not None and returned_model != self._config.model_id:
            raise ReasonerResponseError("reasoner returned a different model")
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ReasonerResponseError("reasoner returned an invalid choice list")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise ReasonerIncompleteError("reasoner generation did not finish normally")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ReasonerResponseError("reasoner returned an invalid assistant message")
        if message.get("refusal") or message.get("tool_calls"):
            raise ReasonerResponseError("reasoner returned a refusal or unsupported tool call")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ReasonerResponseError("reasoner returned empty structured content")
        try:
            parsed_content = json.loads(content)
        except ValueError:
            raise ReasonerResponseError("reasoner returned malformed structured JSON") from None
        try:
            value = output_type.model_validate(parsed_content)
        except ValidationError:
            raise ReasonerOutputValidationError(
                "reasoner output failed structured validation"
            ) from None
        usage = _usage(payload.get("usage"))
        return ReasonerGeneration(
            value=value,
            provider_id=self.provider_id,
            model_id=self._config.model_id,
            finish_reason="stop",
            usage=usage,
        )


def _usage(value: object) -> ReasonerUsage | None:
    if not isinstance(value, dict):
        return None
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    return ReasonerUsage(
        prompt_tokens=prompt if type(prompt) is int and prompt >= 0 else None,
        completion_tokens=completion if type(completion) is int and completion >= 0 else None,
    )
