import pytest

from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import ConfigurationError
from proofbridge_ai.providers import get_embeddings_provider, get_llm_provider
from proofbridge_ai.providers.mock_provider import MockEmbeddingsProvider, MockLLMProvider


def test_defaults():
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_provider == "mock"
    assert settings.embeddings_provider == "mock"
    assert settings.demo_mode is False
    assert settings.similarity_supported_threshold == 0.60
    assert settings.similarity_partial_threshold == 0.40
    assert settings.llm_key_present() is False
    assert settings.embeddings_key_present() is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_SIMILARITY_SUPPORTED_THRESHOLD", "0.70")
    monkeypatch.setenv("PROOFBRIDGE_LLM_MODEL", "test-model")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.similarity_supported_threshold == 0.70
    assert settings.llm_model == "test-model"


def test_threshold_order_invalid(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_SIMILARITY_SUPPORTED_THRESHOLD", "0.30")
    monkeypatch.setenv("PROOFBRIDGE_SIMILARITY_PARTIAL_THRESHOLD", "0.50")
    get_settings.cache_clear()
    with pytest.raises(ConfigurationError):
        get_settings()


def test_threshold_out_of_range_invalid(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_SIMILARITY_PARTIAL_THRESHOLD", "1.5")
    get_settings.cache_clear()
    with pytest.raises(ConfigurationError):
        get_settings()


def test_unknown_provider_invalid(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_LLM_PROVIDER", "anthropic")
    get_settings.cache_clear()
    with pytest.raises(ConfigurationError):
        get_settings()


def test_demo_mode_forces_mock_providers(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_DEMO_MODE", "true")
    monkeypatch.setenv("PROOFBRIDGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PROOFBRIDGE_EMBEDDINGS_PROVIDER", "openai")
    get_settings.cache_clear()
    assert isinstance(get_llm_provider(), MockLLMProvider)
    assert isinstance(get_embeddings_provider(), MockEmbeddingsProvider)


def test_openai_without_key_raises(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PROOFBRIDGE_LLM_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ConfigurationError):
        get_llm_provider(get_settings())
