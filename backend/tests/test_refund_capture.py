"""
Offline mocked unit tests for refund_capture and the refund_capture CLI tool.

All tests run completely offline without hitting PayPal servers.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from paypal_module.paypal_module.payments import refund_capture
from paypal_module.paypal_module.refund_capture import main as cli_main


class MockResponse:
    def __init__(self, status_code, json_data, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or str(json_data)

    def json(self):
        return self._json


def test_refund_capture_full_refund(monkeypatch):
    """Test executing a full refund with default settings."""
    monkeypatch.setattr(
        "paypal_module.paypal_module.payments.get_settings",
        lambda: MagicMock(base_url="https://api-m.sandbox.paypal.com"),
    )
    monkeypatch.setattr(
        "paypal_module.paypal_module.payments.get_access_token",
        lambda: "mock_token",
    )

    mock_post = MagicMock()
    mock_post.return_value = MockResponse(
        201,
        {
            "id": "REFUND-99901",
            "status": "COMPLETED",
            "amount": {"value": "50.00", "currency_code": "USD"},
        },
    )
    monkeypatch.setattr("requests.post", mock_post)

    result = refund_capture("CAP-12345")

    assert result["refund_id"] == "REFUND-99901"
    assert result["status"] == "COMPLETED"
    assert result["amount"] == "50.00"
    assert result["currency"] == "USD"
    assert result["capture_id"] == "CAP-12345"

    assert mock_post.called
    endpoint = mock_post.call_args[0][0]
    assert endpoint == "https://api-m.sandbox.paypal.com/v2/payments/captures/CAP-12345/refund"
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer mock_token"
    assert "PayPal-Request-Id" in headers
    assert "CAP-12345" in headers["PayPal-Request-Id"]


def test_refund_capture_partial_amount(monkeypatch):
    """Test partial refund includes amount and custom note."""
    monkeypatch.setattr(
        "paypal_module.paypal_module.payments.get_settings",
        lambda: MagicMock(base_url="https://api-m.sandbox.paypal.com"),
    )
    monkeypatch.setattr(
        "paypal_module.paypal_module.payments.get_access_token",
        lambda: "mock_token",
    )

    mock_post = MagicMock()
    mock_post.return_value = MockResponse(
        201,
        {
            "id": "REFUND-PARTIAL",
            "status": "COMPLETED",
            "amount": {"value": "20.00", "currency_code": "USD"},
        },
    )
    monkeypatch.setattr("requests.post", mock_post)

    result = refund_capture(
        "CAP-12345",
        amount="20.00",
        currency="USD",
        note="Partial customer refund",
    )

    assert result["refund_id"] == "REFUND-PARTIAL"
    payload = mock_post.call_args[1]["json"]
    assert payload["amount"]["value"] == "20.00"
    assert payload["amount"]["currency_code"] == "USD"
    assert payload["note_to_payer"] == "Partial customer refund"


def test_refund_capture_rejects_empty_id():
    """Test that missing capture_id raises ValueError."""
    with pytest.raises(ValueError, match="A valid capture_id must be provided"):
        refund_capture("   ")


def test_refund_capture_handles_error(monkeypatch):
    """Test handling of PayPal upstream error responses."""
    monkeypatch.setattr(
        "paypal_module.paypal_module.payments.get_settings",
        lambda: MagicMock(base_url="https://api-m.sandbox.paypal.com"),
    )
    monkeypatch.setattr(
        "paypal_module.paypal_module.payments.get_access_token",
        lambda: "mock_token",
    )

    mock_post = MagicMock()
    mock_post.return_value = MockResponse(
        422,
        {
            "message": "CAPTURE_ALREADY_REFUNDED",
            "details": [{"description": "Capture has been refunded"}],
        },
    )
    monkeypatch.setattr("requests.post", mock_post)

    with pytest.raises(RuntimeError, match="CAPTURE_ALREADY_REFUNDED"):
        refund_capture("CAP-12345")


def test_refund_cli_aborts_on_non_confirm(monkeypatch):
    """Test CLI aborts if user does not type REFUND."""
    monkeypatch.setattr(sys, "argv", ["refund_capture.py", "CAP-999"])
    monkeypatch.setattr("builtins.input", lambda _: "NO")

    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 1


def test_refund_cli_executes_on_confirm(monkeypatch):
    """Test CLI executes when user types REFUND."""
    monkeypatch.setattr(sys, "argv", ["refund_capture.py", "CAP-999", "--amount", "15.00"])
    monkeypatch.setattr("builtins.input", lambda _: "REFUND")

    mock_refund = MagicMock(return_value={
        "refund_id": "REFUND-CLI-OK",
        "status": "COMPLETED",
        "amount": "15.00",
        "currency": "USD",
        "capture_id": "CAP-999",
    })
    monkeypatch.setattr("paypal_module.paypal_module.refund_capture.refund_capture", mock_refund)

    result = cli_main()
    assert result == 0
    assert mock_refund.called
