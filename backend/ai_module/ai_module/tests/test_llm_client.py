"""Offline tests for OpenAICompatibleLLMProvider HTTP behavior.

Uses httpx.MockTransport — no network access. Verifies bounded retries on
rate limits/server errors, timeout handling, and that error messages never
contain response bodies.
"""

from __future__ import annotations

import json

import httpx
import pytest

from proofbridge_ai.exceptions import ProviderError, ProviderResponseValidationError
from proofbridge_ai.providers.llm_client import OpenAICompatibleLLMProvider

VALID_BODY = {
    "choices": [{"message": {"content": json.dumps({"requirements": []})}}]
}


def _client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _provider(client: httpx.Client, max_retries: int = 2) -> OpenAICompatibleLLMProvider:
    return OpenAICompatibleLLMProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        max_retries=max_retries,
        client=client,
    )


def _request_counting_handler(statuses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status = statuses[min(len(calls) - 1, len(statuses) - 1)]
        return httpx.Response(status, json=VALID_BODY)

    handler.calls = calls
    return handler


def test_success_first_try(monkeypatch):
    handler = _request_counting_handler([200])
    provider = _provider(_client_with(handler))
    from pydantic import BaseModel, ConfigDict

    class Model(BaseModel):
        model_config = ConfigDict(extra="ignore")
        requirements: list = []

    result = provider.generate_json("system", "user", Model)
    assert result.requirements == []
    assert len(handler.calls) == 1


def test_rate_limit_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("proofbridge_ai.providers.llm_client._retry_backoff", lambda attempt: None)
    handler = _request_counting_handler([429, 429, 200])
    provider = _provider(_client_with(handler))
    from pydantic import BaseModel, ConfigDict

    class Model(BaseModel):
        model_config = ConfigDict(extra="ignore")
        requirements: list = []

    provider.generate_json("system", "user", Model)
    assert len(handler.calls) == 3


def test_server_errors_exhaust_retries_and_raise(monkeypatch):
    monkeypatch.setattr("proofbridge_ai.providers.llm_client._retry_backoff", lambda attempt: None)
    handler = _request_counting_handler([500, 503, 502])
    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderError) as excinfo:
        provider.chat("system", "user")
    assert excinfo.value.provider == "openai"
    assert excinfo.value.status_code == 502
    assert len(handler.calls) == 3  # bounded: 1 + max_retries


def test_client_error_raises_without_retry(monkeypatch):
    monkeypatch.setattr("proofbridge_ai.providers.llm_client._retry_backoff", lambda attempt: None)
    handler = _request_counting_handler([400])
    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderError) as excinfo:
        provider.chat("system", "user")
    assert excinfo.value.status_code == 400
    assert len(handler.calls) == 1


def test_timeout_retries_then_raises(monkeypatch):
    monkeypatch.setattr("proofbridge_ai.providers.llm_client._retry_backoff", lambda attempt: None)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderError) as excinfo:
        provider.chat("system", "user")
    assert excinfo.value.status_code is None
    assert len(calls) == 3


def test_non_json_response_body_raises_validation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error page</html>")

    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderResponseValidationError):
        provider.chat("system", "user")


def test_error_messages_never_contain_response_bodies():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500, text='{"error": "SECRET_USER_DOCUMENT_CONTENT should never leak"}'
        )

    provider = _provider(_client_with(handler))
    with pytest.raises(ProviderError) as excinfo:
        provider.chat("system", "user")
    assert "SECRET_USER_DOCUMENT_CONTENT" not in str(excinfo.value)


def test_validation_retry_appends_error_note(monkeypatch):
    monkeypatch.setattr("proofbridge_ai.providers.llm_client._retry_backoff", lambda attempt: None)
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payloads.append(body)
        if len(payloads) == 1:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "not json at all"}}]}
            )
        return httpx.Response(200, json=VALID_BODY)

    provider = _provider(_client_with(handler))
    from pydantic import BaseModel, ConfigDict

    class Model(BaseModel):
        model_config = ConfigDict(extra="ignore")
        requirements: list = []

    provider.generate_json("system", "user", Model)
    assert len(payloads) == 2
    assert "previous output was invalid" in payloads[1]["messages"][-1]["content"].lower()
