"""OpenAI-compatible chat-completions client (works with any compatible endpoint).

Error handling never logs or raises response bodies: they may contain
untrusted document text. Transient failures (rate limits, 5xx, timeouts)
are retried a bounded number of times with a short backoff.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from proofbridge_ai.exceptions import (
    ConfigurationError,
    ProviderError,
    ProviderResponseValidationError,
)
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.providers.base import BaseLLMProvider, ResponseModelT

logger = get_logger("providers.llm_client")

_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class OpenAICompatibleLLMProvider(BaseLLMProvider):
    """LLM access via the OpenAI chat-completions protocol."""

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
                "An LLM API key is required when PROOFBRIDGE_LLM_PROVIDER='openai'"
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

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        payload = self._build_payload(system_prompt, user_prompt, json_mode=False)
        data = self._post(payload)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseValidationError(
                "Unexpected chat completion response shape", provider=self.name
            ) from exc

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        schema_json = json.dumps(response_model.model_json_schema())
        system_prompt = (
            f"{system_prompt}\nRespond ONLY with a single JSON object conforming "
            f"to this JSON Schema: {schema_json}"
        )
        payload = self._build_payload(system_prompt, user_prompt, json_mode=True)

        for attempt in range(self._max_retries + 1):
            data = self._post(payload)
            try:
                raw = data["choices"][0]["message"]["content"]
                parsed = json.loads(raw)
                return response_model.model_validate(parsed)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                if attempt >= self._max_retries:
                    raise ProviderResponseValidationError(
                        f"Provider output failed validation for {response_model.__name__} "
                        f"after {attempt + 1} attempt(s)",
                        provider=self.name,
                    ) from exc
                payload["messages"][-1]["content"] = (
                    f"{user_prompt}\nYour previous output was invalid "
                    f"({type(exc).__name__}). Please correct it to match the schema."
                )
        raise ProviderResponseValidationError(  # pragma: no cover - unreachable
            f"Provider output failed validation for {response_model.__name__}",
            provider=self.name,
        )

    def _build_payload(
        self, system_prompt: str, user_prompt: str, *, json_mode: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(url, json=payload)
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    logger.warning(
                        "LLM request timed out, retrying: provider=%s attempt=%d",
                        self.name,
                        attempt + 1,
                    )
                    _retry_backoff(attempt)
                    continue
                logger.error("LLM request timed out: provider=%s", self.name)
                raise ProviderError(
                    "LLM request timed out", provider=self.name
                ) from exc
            except httpx.HTTPError as exc:
                logger.error(
                    "LLM transport error: provider=%s error=%s",
                    self.name,
                    type(exc).__name__,
                )
                raise ProviderError(
                    f"LLM transport error: {type(exc).__name__}",
                    provider=self.name,
                ) from exc

            if (
                response.status_code in _RETRYABLE_STATUS_CODES
                and attempt < self._max_retries
            ):
                logger.warning(
                    "LLM request transient failure, retrying: provider=%s "
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
                    "LLM request failed: provider=%s status=%s",
                    self.name,
                    exc.response.status_code,
                )
                raise ProviderError(
                    f"LLM request failed with HTTP {exc.response.status_code}",
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
            "LLM request failed after all retries", provider=self.name
        )


def _retry_backoff(attempt: int) -> None:
    time.sleep(min(0.25 * (2**attempt), 1.0))
