"""Provider selection factories for LLM, embeddings, and vision access.

Demo mode always resolves to the deterministic mock providers regardless of
the configured provider names, so offline testing never needs API keys.
"""

from __future__ import annotations

from functools import lru_cache

from proofbridge_ai.config import Settings, get_settings
from proofbridge_ai.exceptions import ConfigurationError
from proofbridge_ai.providers.base import (
    BaseEmbeddingsProvider,
    BaseLLMProvider,
    BaseVisionProvider,
)


def _build_llm_provider(settings: Settings) -> BaseLLMProvider:
    if settings.demo_mode or settings.llm_provider == "mock":
        from proofbridge_ai.providers.mock_provider import MockLLMProvider

        return MockLLMProvider()
    if settings.llm_provider == "openai":
        from proofbridge_ai.providers.llm_client import OpenAICompatibleLLMProvider

        return OpenAICompatibleLLMProvider(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.max_retries,
        )
    raise ConfigurationError(f"Unknown LLM provider: {settings.llm_provider!r}")


def _build_embeddings_provider(settings: Settings) -> BaseEmbeddingsProvider:
    if settings.demo_mode or settings.embeddings_provider == "mock":
        from proofbridge_ai.providers.mock_provider import MockEmbeddingsProvider

        return MockEmbeddingsProvider()
    if settings.embeddings_provider == "openai":
        from proofbridge_ai.providers.embeddings_client import (
            OpenAICompatibleEmbeddingsProvider,
        )

        return OpenAICompatibleEmbeddingsProvider(
            api_key=settings.embeddings_api_key.get_secret_value(),
            base_url=settings.embeddings_base_url,
            model=settings.embedding_model,
            timeout_seconds=settings.http_timeout_seconds,
        )
    raise ConfigurationError(f"Unknown embeddings provider: {settings.embeddings_provider!r}")


def _build_vision_provider(settings: Settings) -> BaseVisionProvider:
    if settings.demo_mode or settings.vision_provider == "mock":
        from proofbridge_ai.providers.mock_provider import MockVisionProvider

        return MockVisionProvider()
    if settings.vision_provider == "openai":
        from proofbridge_ai.providers.vision_provider import (
            OpenAICompatibleVisionProvider,
        )

        return OpenAICompatibleVisionProvider(
            api_key=settings.vision_api_key.get_secret_value(),
            base_url=settings.vision_base_url,
            model=settings.vision_model,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.max_retries,
        )
    raise ConfigurationError(f"Unknown vision provider: {settings.vision_provider!r}")


@lru_cache(maxsize=1)
def _default_llm_provider() -> BaseLLMProvider:
    return _build_llm_provider(get_settings())


@lru_cache(maxsize=1)
def _default_embeddings_provider() -> BaseEmbeddingsProvider:
    return _build_embeddings_provider(get_settings())


@lru_cache(maxsize=1)
def _default_vision_provider() -> BaseVisionProvider:
    return _build_vision_provider(get_settings())


def get_llm_provider(settings: Settings | None = None) -> BaseLLMProvider:
    """Return the configured LLM provider.

    With ``settings=None`` the result is cached process-wide; passing an
    explicit Settings instance always builds a fresh provider.
    """
    if settings is None:
        return _default_llm_provider()
    return _build_llm_provider(settings)


def get_embeddings_provider(settings: Settings | None = None) -> BaseEmbeddingsProvider:
    """Return the configured embeddings provider (see get_llm_provider)."""
    if settings is None:
        return _default_embeddings_provider()
    return _build_embeddings_provider(settings)


def get_vision_provider(settings: Settings | None = None) -> BaseVisionProvider:
    """Return the configured vision provider (see get_llm_provider)."""
    if settings is None:
        return _default_vision_provider()
    return _build_vision_provider(settings)
