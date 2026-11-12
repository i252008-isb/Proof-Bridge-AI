"""OpenAI-compatible embeddings client (works with any compatible endpoint)."""

from __future__ import annotations

import math
from typing import Any

import httpx

from proofbridge_ai.exceptions import (
    ConfigurationError,
    ProviderError,
    ProviderResponseValidationError,
)
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.providers.base import BaseEmbeddingsProvider

logger = get_logger("providers.embeddings_client")


class OpenAICompatibleEmbeddingsProvider(BaseEmbeddingsProvider):
    """Embedding access via the OpenAI embeddings protocol."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        chunk_size: int = 128,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "An embeddings API key is required when PROOFBRIDGE_EMBEDDINGS_PROVIDER='openai'"
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._chunk_size = chunk_size
        self.dimensions = 0
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self._chunk_size):
            chunk = texts[start : start + self._chunk_size]
            data = self._post(chunk)
            try:
                ordered = sorted(data["data"], key=lambda item: item["index"])
                batch = [item["embedding"] for item in ordered]
            except (KeyError, TypeError) as exc:
                raise ProviderResponseValidationError(
                    "Unexpected embeddings response shape", provider=self.name
                ) from exc
            embeddings.extend(self._normalize(vector) for vector in batch)
        if embeddings and not self.dimensions:
            self.dimensions = len(embeddings[0])
        return embeddings

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return vector
        return [x / norm for x in vector]

    def _post(self, chunk: list[str]) -> dict[str, Any]:
        url = f"{self._base_url}/embeddings"
        try:
            response = self._client.post(url, json={"model": self._model, "input": chunk})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Embeddings request failed: provider=%s status=%s",
                self.name,
                exc.response.status_code,
            )
            raise ProviderError(
                f"Embeddings request failed with HTTP {exc.response.status_code}",
                provider=self.name,
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "Embeddings transport error: provider=%s error=%s",
                self.name,
                type(exc).__name__,
            )
            raise ProviderError(
                f"Embeddings transport error: {type(exc).__name__}", provider=self.name
            ) from exc
        return response.json()
