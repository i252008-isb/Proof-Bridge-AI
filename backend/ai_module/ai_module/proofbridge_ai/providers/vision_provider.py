"""Vision provider: OpenAI-compatible multimodal chat client.

Uses the chat-completions protocol with image_url content parts (data URLs),
so any OpenAI-compatible endpoint with a multimodal model works. Error
handling mirrors the LLM client: response bodies are never logged or
raised, transient failures are retried a bounded number of times.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from proofbridge_ai.config import Settings
from proofbridge_ai.exceptions import (
    ConfigurationError,
    ProviderError,
    ProviderResponseValidationError,
)
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.providers.base import BaseVisionProvider, ResponseModelT, VisionImage

logger = get_logger("providers.vision_client")

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class OpenAICompatibleVisionProvider(BaseVisionProvider):
    """Vision analysis via the OpenAI chat-completions protocol."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "A vision API key is required when PROOFBRIDGE_VISION_PROVIDER='openai'"
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    def analyze_images(
        self,
        images: list[VisionImage],
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        schema_json = json.dumps(response_model.model_json_schema())
        system_prompt = (
            f"{system_prompt}\nRespond ONLY with a single JSON object conforming "
            f"to this JSON Schema: {schema_json}"
        )
        payload = self._build_payload(images, system_prompt, user_prompt)

        for attempt in range(self._max_retries + 1):
            data = self._post(payload)
            try:
                raw = data["choices"][0]["message"]["content"]
                parsed = json.loads(raw)
                return response_model.model_validate(parsed)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                if attempt >= self._max_retries:
                    raise ProviderResponseValidationError(
                        f"Vision provider output failed validation for "
                        f"{response_model.__name__} after {attempt + 1} attempt(s)",
                        provider=self.name,
                    ) from exc
                payload["messages"][-1]["content"] = [
                    *[part for part in payload["messages"][-1]["content"] if part["type"] != "text"],
                    {
                        "type": "text",
                        "text": (
                            f"{user_prompt}\nYour previous output was invalid "
                            f"({type(exc).__name__}). Please correct it to match the schema."
                        ),
                    },
                ]
        raise ProviderResponseValidationError(  # pragma: no cover - unreachable
            f"Vision provider output failed validation for {response_model.__name__}",
            provider=self.name,
        )

    def _build_payload(
        self,
        images: list[VisionImage],
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        content_parts: list[dict[str, Any]] = [
            {"type": "text", "text": user_prompt}
        ]
        for image in images:
            encoded = base64.b64encode(image.image_bytes).decode("ascii")
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.media_type};base64,{encoded}",
                    },
                }
            )
        return {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_parts},
            ],
            "response_format": {"type": "json_object"},
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(url, json=payload)
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    logger.warning(
                        "Vision request timed out, retrying: provider=%s attempt=%d",
                        self.name,
                        attempt + 1,
                    )
                    _retry_backoff(attempt)
                    continue
                logger.error("Vision request timed out: provider=%s", self.name)
                raise ProviderError(
                    "Vision request timed out", provider=self.name
                ) from exc
            except httpx.HTTPError as exc:
                logger.error(
                    "Vision transport error: provider=%s error=%s",
                    self.name,
                    type(exc).__name__,
                )
                raise ProviderError(
                    f"Vision transport error: {type(exc).__name__}",
                    provider=self.name,
                ) from exc

            if (
                response.status_code in _RETRYABLE_STATUS_CODES
                and attempt < self._max_retries
            ):
                logger.warning(
                    "Vision request transient failure, retrying: provider=%s "
                    "status=%s attempt=%d",
                    self.name,
                    response.status_code,
                    attempt + 1,
                )
                _retry_backoff(attempt)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Vision request failed: provider=%s status=%s",
                    self.name,
                    exc.response.status_code,
                )
                raise ProviderError(
                    f"Vision request failed with HTTP {exc.response.status_code}",
                    provider=self.name,
                    status_code=exc.response.status_code,
                ) from exc

            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise ProviderResponseValidationError(
                    "Provider response body was not valid JSON",
                    provider=self.name,
                ) from exc

        raise ProviderError(  # pragma: no cover - unreachable
            "Vision request failed after all retries", provider=self.name
        )


def _retry_backoff(attempt: int) -> None:
    time.sleep(min(0.25 * (2**attempt), 1.0))


def get_vision_provider(settings: Settings) -> BaseVisionProvider:
    """Build the configured vision provider (lru_cached by the factory).

    Demo mode or ``PROOFBRIDGE_VISION_PROVIDER=mock`` returns the clearly
    labeled mock provider; ``openai`` requires an API key.
    """
    if settings.demo_mode or settings.vision_provider == "mock":
        from proofbridge_ai.providers.mock_provider import MockVisionProvider

        return MockVisionProvider()
    if settings.vision_provider == "openai":
        return OpenAICompatibleVisionProvider(
            api_key=settings.vision_api_key.get_secret_value(),
            base_url=settings.vision_base_url,
            model=settings.vision_model,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.max_retries,
        )
    raise ConfigurationError(
        f"Unknown vision provider: {settings.vision_provider!r}"
    )
