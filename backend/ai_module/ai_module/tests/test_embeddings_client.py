"""Offline tests for OpenAICompatibleEmbeddingsProvider HTTP behavior.

Uses httpx.MockTransport — no network access. Verifies chunking, index
re-ordering, normalization, and error mapping (missing key, HTTP failure,
transport failure, unexpected response shape).
"""

from __future__ import annotations

import httpx
import pytest

from proofbridge_ai.exceptions import (
    ConfigurationError,
    ProviderError,
    ProviderResponseValidationError,
)
from proofbridge_ai.providers.embeddings_client import OpenAICompatibleEmbeddingsProvider


def _client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _provider(client: httpx.Client, **kwargs) -> OpenAICompatibleEmbeddingsProvider:
    defaults = dict(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-embed",
    )
    defaults.update(kwargs)
    return OpenAICompatibleEmbeddingsProvider(client=client, **defaults)


def _embedding_response(vectors: list[list[float]]) -> dict:
    return {
        "data": [
            {"index": index, "embedding": vector} for index, vector in enumerate(vectors)
        ]
    }


def test_requires_api_key():
    with pytest.raises(ConfigurationError):
        OpenAICompatibleEmbeddingsProvider(
            api_key="",
            base_url="https://example.test/v1",
            model="test-embed",
        )


def test_embeds_and_normalizes_vectors():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(200, json=_embedding_response([[3.0, 4.0], [1.0, 0.0]]))

    provider = _provider(_client_with(handler))
    vectors = provider.embed_texts(["a", "b"])

    assert len(vectors) == 2
    assert vectors[0] == pytest.approx([0.6, 0.8])
    assert vectors[1] == pytest.approx([1.0, 0.0])
    assert provider.dimensions == 2


def test_reorders_by_index_and_chunks():
    import json

    captured: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        batch = json.loads(request.content)["input"]
        captured.extend(batch)
        return httpx.Response(
            200, json=_embedding_response([[0.0, 1.0] for _ in batch])
        )

    provider = _provider(_client_with(capture), chunk_size=2)
    vectors = provider.embed_texts(["t1", "t2", "t3"])

    assert captured == ["t1", "t2", "t3"]
    assert len(vectors) == 3


def test_out_of_order_indices_are_sorted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    provider = _provider(_client_with(handler))
    vectors = provider.embed_texts(["a", "b"])

    assert vectors[0] == pytest.approx([1.0, 0.0])
    assert vectors[1] == pytest.approx([0.0, 1.0])


def test_http_failure_raises_provider_error_with_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderError) as excinfo:
        provider.embed_texts(["a"])
    assert excinfo.value.status_code == 401
    assert "unauthorized" not in str(excinfo.value)


def test_transport_error_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderError) as excinfo:
        provider.embed_texts(["a"])
    assert "ConnectError" in str(excinfo.value)


def test_unexpected_shape_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderResponseValidationError):
        provider.embed_texts(["a"])


def test_empty_input_returns_empty_list():
    provider = _provider(_client_with(lambda request: httpx.Response(500)))
    assert provider.embed_texts([]) == []


def test_zero_vector_is_returned_unchanged():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embedding_response([[0.0, 0.0]]))

    provider = _provider(_client_with(handler))
    assert provider.embed_texts(["a"]) == [[0.0, 0.0]]
