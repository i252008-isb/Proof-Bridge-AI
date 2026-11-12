from decimal import Decimal

import httpx
import pytest

from app.config import Settings
from app.main import app
from app.models import PayPalTransaction
from app.security import ROLE_CLIENT, ROLE_FREELANCER, ROLE_REVIEWER
from app.services.paypal_service import (
    PayPalClient,
    derive_payment_state,
    get_paypal_client_dependency,
)

from tests.helpers import (
    auth_headers,
    create_user,
    login_token,
    make_project,
)


ORDER_ID = "ORDER-123"
CAPTURE_ID = "CAPTURE-123"
AUTHORIZATION_ID = "AUTH-123"
PAYER_EMAIL = "private-payer@example.com"


def _order_payload(order_id=ORDER_ID, status="APPROVED", intent="AUTHORIZE"):
    return {
        "id": order_id,
        "status": status,
        "intent": intent,
        "purchase_units": [
            {
                "reference_id": "CASE-001",
                "amount": {"currency_code": "USD", "value": "75.50"},
            }
        ],
        "payer": {
            "email_address": PAYER_EMAIL,
            "name": {"given_name": "Private", "surname": "Payer"},
        },
        "create_time": "2026-11-01T10:00:00Z",
        "update_time": "2026-11-01T10:01:00Z",
    }


def _order_with_payments(order_id, status, intent, payments):
    payload = _order_payload(order_id, status, intent)
    payload["purchase_units"][0]["payments"] = payments
    return payload


def _capture_payload(capture_id=CAPTURE_ID):
    return {
        "id": capture_id,
        "status": "COMPLETED",
        "amount": {"currency_code": "USD", "value": "75.50"},
        "final_capture": True,
        "create_time": "2026-11-01T10:00:00Z",
        "update_time": "2026-11-01T10:01:00Z",
    }


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeHTTPClient:
    def __init__(
        self,
        lookup_response=None,
        token_response=None,
        get_error=None,
    ):
        self.lookup_response = lookup_response or _FakeResponse(
            200, _order_payload()
        )
        self.token_response = token_response or _FakeResponse(
            200, {"access_token": "test-access-token"}
        )
        self.get_error = get_error
        self.calls = []
        self.get_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return self.token_response

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs.get("headers")))
        self.get_count += 1

        if self.get_error is not None:
            raise self.get_error

        return self.lookup_response


def _settings(**overrides):
    values = {
        "SECRET_KEY": "test-secret",
        "PAYPAL_CLIENT_ID": "client-id-123",
        "PAYPAL_CLIENT_SECRET": "client-secret-456",
        "PAYPAL_API_BASE": "https://api-m.sandbox.paypal.com",
        "PAYPAL_TIMEOUT_SECONDS": 5,
    }
    values.update(overrides)

    return Settings(**values)


def _install_client(fake_http, **settings_overrides):
    paypal = PayPalClient(
        settings=_settings(**settings_overrides),
        http_client_factory=lambda **kwargs: fake_http,
    )
    app.dependency_overrides[get_paypal_client_dependency] = lambda: paypal

    return paypal


def _project(db, prefix="p4-paypal"):
    owner = create_user(db, f"{prefix}-owner", ROLE_CLIENT)
    freelancer = create_user(db, f"{prefix}-fl", ROLE_FREELANCER)
    project = make_project(db, "Person 4 PayPal", owner.id, freelancer.id)

    return owner, freelancer, project


def _sync_order(client, token, project_id, order_id=ORDER_ID):
    return client.post(
        f"/projects/{project_id}/paypal/orders/sync",
        json={"order_id": order_id},
        headers=auth_headers(token),
    )


def _sync_capture(client, token, project_id, capture_id=CAPTURE_ID):
    return client.post(
        f"/projects/{project_id}/paypal/transactions/sync",
        json={"transaction_id": capture_id},
        headers=auth_headers(token),
    )


def test_order_sync_stores_sanitized_read_only_information(client, db):
    owner, _, project = _project(db)
    token = login_token(client, owner.email)

    fake_http = _FakeHTTPClient()
    _install_client(fake_http)

    response = _sync_order(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["created"] is True
    transaction = body["transaction"]
    assert transaction["project_id"] == project.id
    assert transaction["paypal_transaction_id"] == ORDER_ID
    assert transaction["amount"] == 75.5
    assert transaction["currency"] == "USD"
    assert transaction["status"] == "APPROVED"
    assert transaction["information_type"] == "order"
    assert transaction["intent"] == "AUTHORIZE"
    assert transaction["payment_state"] == "APPROVED"
    assert transaction["authorization_id"] is None
    assert transaction["authorization_status"] is None
    assert transaction["capture_id"] is None
    assert transaction["case_reference"] == "CASE-001"
    assert transaction["provider"] == "paypal"
    assert "does not mean ProofBridge holds" in (
        transaction["money_control_notice"]
    )

    assert set(transaction["raw_data"]) == {
        "id",
        "status",
        "payment_state",
        "intent",
        "reference_id",
        "create_time",
        "update_time",
    }
    assert "payer" not in transaction["raw_data"]
    assert PAYER_EMAIL not in response.text

    db.expire_all()
    stored = db.query(PayPalTransaction).one()
    assert stored.project_id == project.id
    assert stored.paypal_transaction_id == ORDER_ID
    assert stored.amount == Decimal("75.50")
    assert stored.currency == "USD"
    assert stored.status == "APPROVED"
    assert "payer" not in stored.raw_data
    assert PAYER_EMAIL not in str(stored.raw_data)

    assert fake_http.calls[0][0] == "POST"
    assert fake_http.calls[0][1].endswith("/v1/oauth2/token")
    assert fake_http.calls[1][0] == "GET"
    assert fake_http.calls[1][1].endswith(
        f"/v2/checkout/orders/{ORDER_ID}"
    )

    duplicate = _sync_order(client, token, project.id)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["created"] is False
    assert duplicate.json()["transaction"]["id"] == transaction["id"]
    assert fake_http.get_count == 1
    assert db.query(PayPalTransaction).count() == 1

    single = client.get(
        f"/projects/{project.id}/paypal/transactions/{ORDER_ID}",
        headers=auth_headers(token),
    )
    assert single.status_code == 200, single.text
    assert single.json()["payment_state"] == "APPROVED"

    listing = client.get(
        f"/projects/{project.id}/paypal/transactions",
        headers=auth_headers(token),
    )
    assert listing.status_code == 200, listing.text
    assert [row["paypal_transaction_id"] for row in listing.json()] == [
        ORDER_ID
    ]


def test_order_sync_maps_held_and_paid_states(client, db):
    owner, _, project = _project(db, "p4-paypal-states")
    token = login_token(client, owner.email)

    held_id = "ORDER-HELD"
    held_payload = _order_with_payments(
        held_id,
        "COMPLETED",
        "AUTHORIZE",
        {"authorizations": [{"id": AUTHORIZATION_ID, "status": "CREATED"}]},
    )
    _install_client(
        _FakeHTTPClient(lookup_response=_FakeResponse(200, held_payload))
    )

    held = _sync_order(client, token, project.id, held_id)
    assert held.status_code == 201, held.text
    held_tx = held.json()["transaction"]
    assert held_tx["payment_state"] == "HELD"
    assert held_tx["authorization_id"] == AUTHORIZATION_ID
    assert held_tx["authorization_status"] == "CREATED"

    paid_id = "ORDER-PAID"
    paid_payload = _order_with_payments(
        paid_id,
        "COMPLETED",
        "CAPTURE",
        {"captures": [{"id": CAPTURE_ID, "status": "COMPLETED"}]},
    )
    _install_client(
        _FakeHTTPClient(lookup_response=_FakeResponse(200, paid_payload))
    )

    paid = _sync_order(client, token, project.id, paid_id)
    assert paid.status_code == 201, paid.text
    paid_tx = paid.json()["transaction"]
    assert paid_tx["payment_state"] == "PAID"
    assert paid_tx["capture_id"] == CAPTURE_ID
    assert paid_tx["intent"] == "CAPTURE"


def test_order_sync_is_idempotent_and_cannot_move_between_projects(
    client, db
):
    owner, freelancer, first = _project(db, "p4-paypal-dupe")
    second = make_project(
        db, "Person 4 PayPal second", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)

    fake_http = _FakeHTTPClient()
    _install_client(fake_http)

    original = _sync_order(client, token, first.id)
    assert original.status_code == 201, original.text

    conflict = _sync_order(client, token, second.id)
    assert conflict.status_code == 409
    assert "another project" in conflict.json()["error"]["message"].lower()

    db.expire_all()
    stored = db.query(PayPalTransaction).one()
    assert stored.project_id == first.id
    assert fake_http.get_count == 1

    scoped = client.get(
        f"/projects/{second.id}/paypal/transactions/{ORDER_ID}",
        headers=auth_headers(token),
    )
    assert scoped.status_code == 404


def test_order_and_capture_sync_do_not_create_duplicate_records(client, db):
    owner, freelancer, order_project = _project(db, "p4-paypal-order-first")
    capture_project = make_project(
        db, "Person 4 PayPal capture first", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)

    order_with_capture = _order_with_payments(
        "ORDER-WITH-CAPTURE",
        "COMPLETED",
        "CAPTURE",
        {"captures": [{"id": CAPTURE_ID, "status": "COMPLETED"}]},
    )
    _install_client(
        _FakeHTTPClient(
            lookup_response=_FakeResponse(200, order_with_capture)
        )
    )

    order_sync = _sync_order(
        client, token, order_project.id, "ORDER-WITH-CAPTURE"
    )
    assert order_sync.status_code == 201, order_sync.text

    duplicate_capture = _sync_capture(
        client, token, order_project.id, CAPTURE_ID
    )
    assert duplicate_capture.status_code == 409
    assert "already recorded" in (
        duplicate_capture.json()["error"]["message"].lower()
    )

    second_capture_id = "CAPTURE-999"
    _install_client(
        _FakeHTTPClient(
            lookup_response=_FakeResponse(
                200, _capture_payload(second_capture_id)
            )
        )
    )
    capture_sync = _sync_capture(
        client, token, capture_project.id, second_capture_id
    )
    assert capture_sync.status_code == 201, capture_sync.text
    assert capture_sync.json()["transaction"]["information_type"] == (
        "capture"
    )

    order_with_existing_capture = _order_with_payments(
        "ORDER-AFTER-CAPTURE",
        "COMPLETED",
        "CAPTURE",
        {"captures": [{"id": second_capture_id, "status": "COMPLETED"}]},
    )
    _install_client(
        _FakeHTTPClient(
            lookup_response=_FakeResponse(
                200, order_with_existing_capture
            )
        )
    )
    duplicate_order = _sync_order(
        client, token, capture_project.id, "ORDER-AFTER-CAPTURE"
    )
    assert duplicate_order.status_code == 409
    assert "already recorded" in (
        duplicate_order.json()["error"]["message"].lower()
    )

    db.expire_all()
    assert db.query(PayPalTransaction).count() == 2


def test_order_sync_failures_store_nothing(client, db):
    owner, _, project = _project(db, "p4-paypal-errors")
    token = login_token(client, owner.email)

    cases = [
        ("not-found", _FakeHTTPClient(lookup_response=_FakeResponse(404, {})), 404),
        (
            "auth-failure",
            _FakeHTTPClient(token_response=_FakeResponse(401, {})),
            502,
        ),
        (
            "upstream-failure",
            _FakeHTTPClient(lookup_response=_FakeResponse(500, {})),
            502,
        ),
        (
            "network-failure",
            _FakeHTTPClient(get_error=httpx.ConnectError("network down")),
            502,
        ),
        (
            "unreadable",
            _FakeHTTPClient(lookup_response=_FakeResponse(200, [])),
            502,
        ),
        (
            "incomplete",
            _FakeHTTPClient(
                lookup_response=_FakeResponse(
                    200, {"id": ORDER_ID, "status": "APPROVED"}
                )
            ),
            502,
        ),
        (
            "wrong-order",
            _FakeHTTPClient(
                lookup_response=_FakeResponse(
                    200, _order_payload("OTHER-ORDER")
                )
            ),
            502,
        ),
        (
            "bad-amount",
            _FakeHTTPClient(
                lookup_response=_FakeResponse(
                    200,
                    {
                        "id": ORDER_ID,
                        "status": "APPROVED",
                        "purchase_units": [
                            {
                                "amount": {
                                    "currency_code": "USD",
                                    "value": "not-a-number",
                                }
                            }
                        ],
                    },
                )
            ),
            502,
        ),
        (
            "bad-currency",
            _FakeHTTPClient(
                lookup_response=_FakeResponse(
                    200,
                    {
                        "id": ORDER_ID,
                        "status": "APPROVED",
                        "purchase_units": [
                            {
                                "amount": {
                                    "currency_code": "US",
                                    "value": "10.00",
                                }
                            }
                        ],
                    },
                )
            ),
            502,
        ),
    ]

    for name, fake_http, expected_status in cases:
        _install_client(fake_http)
        response = _sync_order(client, token, project.id)

        assert response.status_code == expected_status, (name, response.text)
        assert db.query(PayPalTransaction).count() == 0, name


def test_order_sync_config_and_roles(client, db):
    owner, freelancer, project = _project(db, "p4-paypal-auth")
    reviewer = create_user(db, "p4-paypal-reviewer", ROLE_REVIEWER)
    outsider = create_user(db, "p4-paypal-outsider", ROLE_CLIENT)
    outsider_freelancer = create_user(
        db, "p4-paypal-outsider-fl", ROLE_FREELANCER
    )
    outsider_project = make_project(
        db, "Person 4 PayPal outsider", outsider.id, outsider_freelancer.id
    )

    _install_client(
        _FakeHTTPClient(),
        PAYPAL_CLIENT_ID=None,
        PAYPAL_CLIENT_SECRET=None,
    )

    for token in (
        login_token(client, freelancer.email),
        login_token(client, reviewer.email),
        login_token(client, outsider.email),
    ):
        response = _sync_order(client, token, project.id)
        assert response.status_code == 403

    owner_token = login_token(client, owner.email)
    assert _sync_order(client, owner_token, project.id).status_code == 503

    unauthenticated = client.post(
        f"/projects/{project.id}/paypal/orders/sync",
        json={"order_id": ORDER_ID},
    )
    assert unauthenticated.status_code == 401

    owner_fake = _FakeHTTPClient()
    _install_client(owner_fake)
    ok = _sync_order(client, owner_token, project.id)
    assert ok.status_code == 201, ok.text
    assert "client-id-123" not in ok.text
    assert "client-secret-456" not in ok.text

    reviewer_token = login_token(client, reviewer.email)
    reviewer_list = client.get(
        f"/projects/{project.id}/paypal/transactions",
        headers=auth_headers(reviewer_token),
    )
    assert reviewer_list.status_code == 200
    assert len(reviewer_list.json()) == 1

    freelancer_list = client.get(
        f"/projects/{project.id}/paypal/transactions",
        headers=auth_headers(login_token(client, freelancer.email)),
    )
    assert freelancer_list.status_code == 200
    assert len(freelancer_list.json()) == 1

    outsider_token = login_token(client, outsider.email)
    assert (
        client.get(
            f"/projects/{project.id}/paypal/transactions",
            headers=auth_headers(outsider_token),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/projects/{outsider_project.id}/paypal/transactions",
            headers=auth_headers(owner_token),
        ).status_code
        == 403
    )


def test_order_sync_request_validation(client, db):
    owner, _, project = _project(db, "p4-paypal-validation")
    token = login_token(client, owner.email)

    fake_http = _FakeHTTPClient()
    _install_client(fake_http)

    base = f"/projects/{project.id}/paypal/orders/sync"
    headers = auth_headers(token)

    assert client.post(base, json={}, headers=headers).status_code == 422
    assert (
        client.post(base, json={"order_id": "   "}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            base,
            json={"order_id": ORDER_ID, "extra": "x"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            base,
            json={"order_id": "x" * 256},
            headers=headers,
        ).status_code
        == 422
    )
    assert fake_http.get_count == 0
    assert db.query(PayPalTransaction).count() == 0


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "status": "CREATED",
                "intent": "CAPTURE",
                "purchase_units": [
                    {"amount": {"currency_code": "USD", "value": "10.00"}}
                ],
            },
            "PENDING_APPROVAL",
        ),
        (
            {
                "status": "APPROVED",
                "intent": "CAPTURE",
                "purchase_units": [
                    {"amount": {"currency_code": "USD", "value": "10.00"}}
                ],
            },
            "APPROVED",
        ),
        (
            {
                "status": "COMPLETED",
                "intent": "AUTHORIZE",
                "purchase_units": [
                    {
                        "payments": {
                            "authorizations": [
                                {"id": "AUTH", "status": "CREATED"}
                            ]
                        }
                    }
                ],
            },
            "HELD",
        ),
        (
            {
                "status": "COMPLETED",
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {"id": "CAP", "status": "COMPLETED"}
                            ]
                        }
                    }
                ],
            },
            "PAID",
        ),
        (
            {
                "status": "COMPLETED",
                "intent": "AUTHORIZE",
                "purchase_units": [
                    {
                        "payments": {
                            "authorizations": [
                                {"id": "AUTH", "status": "VOIDED"}
                            ]
                        }
                    }
                ],
            },
            "VOIDED",
        ),
        (
            {"status": "EXPIRED", "expiration_time": "2026-11-01T10:00:00Z"},
            "EXPIRED",
        ),
        (
            {"status": "DENIED", "expiration_time": "2026-11-01T10:00:00Z"},
            "FAILED",
        ),
        (
            {
                "status": "COMPLETED",
                "final_capture": True,
                "amount": {"currency_code": "USD", "value": "10.00"},
            },
            "PAID",
        ),
    ],
)
def test_derive_payment_state_normalization(payload, expected):
    assert derive_payment_state(payload) == expected
