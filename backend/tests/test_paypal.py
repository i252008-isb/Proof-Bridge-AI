from decimal import Decimal

import httpx

from app.config import Settings
from app.main import app
from app.models import PayPalTransaction
from app.security import ROLE_CLIENT, ROLE_FREELANCER, ROLE_REVIEWER
from app.services.paypal_service import (
    PayPalClient,
    get_paypal_client_dependency,
)

from tests.helpers import (
    auth_headers,
    create_user,
    login_token,
    make_project,
)


CAPTURE_ID = "CAPTURE-123"
CAPTURE_PAYLOAD = {
    "id": CAPTURE_ID,
    "status": "COMPLETED",
    "amount": {"currency_code": "USD", "value": "49.99"},
    "final_capture": True,
    "create_time": "2026-11-01T10:00:00Z",
    "update_time": "2026-11-01T10:01:00Z",
    "payer": {
        "email_address": "private-payer@example.com",
        "name": {"given_name": "Private", "surname": "Payer"},
    },
}


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHTTPClient:
    def __init__(
        self,
        capture_response=None,
        token_response=None,
        get_error=None,
    ):
        self.capture_response = capture_response or _FakeResponse(
            200, CAPTURE_PAYLOAD
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
        return self.capture_response


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


def _sync(client, token, project_id, transaction_id=CAPTURE_ID):
    return client.post(
        f"/projects/{project_id}/paypal/transactions/sync",
        json={"transaction_id": transaction_id},
        headers=auth_headers(token),
    )


def test_paypal_sync_stores_sanitized_read_only_information(client, db):
    owner = create_user(db, "p9-paypal-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-paypal-fl", ROLE_FREELANCER)
    project = make_project(db, "PayPal project", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    fake_http = _FakeHTTPClient()
    _install_client(fake_http)

    response = _sync(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["created"] is True
    transaction = body["transaction"]
    assert transaction["project_id"] == project.id
    assert transaction["paypal_transaction_id"] == CAPTURE_ID
    assert transaction["amount"] == 49.99
    assert transaction["currency"] == "USD"
    assert transaction["status"] == "COMPLETED"
    assert transaction["provider"] == "paypal"
    assert "does not mean ProofBridge holds" in (
        transaction["money_control_notice"]
    )
    assert set(transaction["raw_data"]) == {
        "id",
        "status",
        "amount",
        "final_capture",
        "create_time",
        "update_time",
    }
    assert "payer" not in transaction["raw_data"]
    assert "private-payer@example.com" not in response.text

    db.expire_all()
    stored = db.query(PayPalTransaction).one()
    assert stored.project_id == project.id
    assert stored.paypal_transaction_id == CAPTURE_ID
    assert stored.amount == Decimal("49.99")
    assert stored.currency == "USD"
    assert stored.status == "COMPLETED"
    assert "payer" not in stored.raw_data

    assert fake_http.calls[0][0] == "POST"
    assert fake_http.calls[0][1].endswith("/v1/oauth2/token")
    assert fake_http.calls[1][0] == "GET"
    assert fake_http.calls[1][1].endswith(
        f"/v2/payments/captures/{CAPTURE_ID}"
    )

    duplicate = _sync(client, token, project.id)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["created"] is False
    assert duplicate.json()["transaction"]["id"] == transaction["id"]
    assert fake_http.get_count == 1
    assert db.query(PayPalTransaction).count() == 1

    listing = client.get(
        f"/projects/{project.id}/paypal/transactions",
        headers=auth_headers(token),
    )
    assert listing.status_code == 200, listing.text
    assert [row["paypal_transaction_id"] for row in listing.json()] == [
        CAPTURE_ID
    ]

    single = client.get(
        f"/projects/{project.id}/paypal/transactions/{CAPTURE_ID}",
        headers=auth_headers(token),
    )
    assert single.status_code == 200, single.text
    assert single.json()["id"] == transaction["id"]


def test_paypal_missing_configuration_is_reported_without_secrets(client, db):
    owner = create_user(db, "p9-paypal-config-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-paypal-config-fl", ROLE_FREELANCER)
    project = make_project(db, "PayPal config", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    _install_client(
        _FakeHTTPClient(),
        PAYPAL_CLIENT_ID=None,
        PAYPAL_CLIENT_SECRET=None,
    )

    response = _sync(client, token, project.id)
    assert response.status_code == 503
    message = response.json()["error"]["message"]
    assert "PAYPAL_CLIENT_ID" in message
    assert "PAYPAL_CLIENT_SECRET" in message
    assert "client-secret-456" not in message
    assert db.query(PayPalTransaction).count() == 0

    status_response = client.get(
        f"/projects/{project.id}/paypal/status",
        headers=auth_headers(token),
    )
    assert status_response.status_code == 200, status_response.text
    body = status_response.json()
    assert body["configured"] is False
    assert body["environment"] == "sandbox"
    assert body["lookup_mode"] == "read_only_transaction_information"
    assert "client-id-123" not in status_response.text
    assert "client-secret-456" not in status_response.text


def test_paypal_not_found_and_upstream_errors_store_nothing(client, db):
    owner = create_user(db, "p9-paypal-error-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-paypal-error-fl", ROLE_FREELANCER)
    project = make_project(db, "PayPal errors", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    _install_client(
        _FakeHTTPClient(capture_response=_FakeResponse(404, {}))
    )
    not_found = _sync(client, token, project.id)
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "not_found"

    _install_client(
        _FakeHTTPClient(token_response=_FakeResponse(401, {}))
    )
    auth_failure = _sync(client, token, project.id)
    assert auth_failure.status_code == 502
    assert db.query(PayPalTransaction).count() == 0

    _install_client(
        _FakeHTTPClient(capture_response=_FakeResponse(500, {}))
    )
    upstream = _sync(client, token, project.id)
    assert upstream.status_code == 502
    assert db.query(PayPalTransaction).count() == 0

    _install_client(
        _FakeHTTPClient(get_error=httpx.ConnectError("network down"))
    )
    network = _sync(client, token, project.id)
    assert network.status_code == 502
    assert db.query(PayPalTransaction).count() == 0


def test_paypal_incomplete_response_is_rejected(client, db):
    owner = create_user(db, "p9-paypal-bad-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-paypal-bad-fl", ROLE_FREELANCER)
    project = make_project(db, "PayPal bad payload", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    _install_client(
        _FakeHTTPClient(
            capture_response=_FakeResponse(
                200,
                {
                    "id": CAPTURE_ID,
                    "status": "COMPLETED",
                },
            )
        )
    )
    response = _sync(client, token, project.id)

    assert response.status_code == 502
    assert "incomplete" in response.json()["error"]["message"].lower()
    assert db.query(PayPalTransaction).count() == 0

    _install_client(
        _FakeHTTPClient(
            token_response=_FakeResponse(200, {"token_type": "Bearer"})
        )
    )
    missing_token = _sync(client, token, project.id)
    assert missing_token.status_code == 502
    assert db.query(PayPalTransaction).count() == 0

    mismatched = dict(CAPTURE_PAYLOAD)
    mismatched["id"] = "DIFFERENT-CAPTURE"
    _install_client(
        _FakeHTTPClient(
            capture_response=_FakeResponse(200, mismatched)
        )
    )
    wrong_id = _sync(client, token, project.id)
    assert wrong_id.status_code == 502
    assert "different transaction" in wrong_id.json()["error"]["message"].lower()
    assert db.query(PayPalTransaction).count() == 0


def test_paypal_transaction_cannot_move_between_projects(client, db):
    owner = create_user(db, "p9-paypal-dupe-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-paypal-dupe-fl", ROLE_FREELANCER)
    first = make_project(db, "PayPal first", owner.id, freelancer.id)
    second = make_project(db, "PayPal second", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    fake_http = _FakeHTTPClient()
    _install_client(fake_http)

    original = _sync(client, token, first.id)
    assert original.status_code == 201, original.text

    conflict = _sync(client, token, second.id)
    assert conflict.status_code == 409
    assert "another project" in conflict.json()["error"]["message"].lower()

    db.expire_all()
    stored = db.query(PayPalTransaction).one()
    assert stored.project_id == first.id
    assert fake_http.get_count == 1

    scoped = client.get(
        f"/projects/{second.id}/paypal/transactions/{CAPTURE_ID}",
        headers=auth_headers(token),
    )
    assert scoped.status_code == 404


def test_paypal_sync_is_owner_only_and_reads_are_project_scoped(client, db):
    owner = create_user(db, "p9-paypal-auth-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-paypal-auth-fl", ROLE_FREELANCER)
    project = make_project(db, "PayPal auth", owner.id, freelancer.id)
    reviewer = create_user(db, "p9-paypal-auth-rev", ROLE_REVIEWER)
    outsider = create_user(db, "p9-paypal-auth-out", ROLE_CLIENT)
    outsider_freelancer = create_user(
        db, "p9-paypal-auth-out-fl", ROLE_FREELANCER
    )
    outsider_project = make_project(
        db, "PayPal outsider", outsider.id, outsider_freelancer.id
    )

    _install_client(
        _FakeHTTPClient(),
        PAYPAL_CLIENT_ID=None,
        PAYPAL_CLIENT_SECRET=None,
    )

    for token in (
        login_token(client, freelancer.email),
        login_token(client, outsider.email),
        login_token(client, reviewer.email),
    ):
        response = _sync(client, token, project.id)
        assert response.status_code == 403

    assert _sync(
        client, login_token(client, owner.email), project.id
    ).status_code == 503

    assert (
        client.post(
            f"/projects/{project.id}/paypal/transactions/sync",
            json={"transaction_id": CAPTURE_ID},
        ).status_code
        == 401
    )

    owner_fake = _FakeHTTPClient()
    _install_client(owner_fake)
    ok = _sync(client, login_token(client, owner.email), project.id)
    assert ok.status_code == 201, ok.text

    reviewer_token = login_token(client, reviewer.email)
    reviewer_list = client.get(
        f"/projects/{project.id}/paypal/transactions",
        headers=auth_headers(reviewer_token),
    )
    assert reviewer_list.status_code == 200
    assert len(reviewer_list.json()) == 1

    outsider_token = login_token(client, outsider.email)
    assert (
        client.get(
            f"/projects/{project.id}/paypal/transactions",
            headers=auth_headers(outsider_token),
        ).status_code
        == 403
    )
    owner_token = login_token(client, owner.email)
    assert (
        client.get(
            f"/projects/{outsider_project.id}/paypal/transactions",
            headers=auth_headers(owner_token),
        ).status_code
        == 403
    )


def test_paypal_surface_contains_no_money_movement_endpoints():
    paths = app.openapi()["paths"]
    paypal_paths = {
        path: methods
        for path, methods in paths.items()
        if "/paypal/" in path
    }

    assert set(paypal_paths) == {
        "/projects/{project_id}/paypal/status",
        "/projects/{project_id}/paypal/orders/sync",
        "/projects/{project_id}/paypal/transactions",
        "/projects/{project_id}/paypal/transactions/sync",
        "/projects/{project_id}/paypal/transactions/{transaction_id}",
    }
    assert set(
        paypal_paths["/projects/{project_id}/paypal/transactions/sync"]
    ) == {"post"}
    assert set(
        paypal_paths["/projects/{project_id}/paypal/orders/sync"]
    ) == {"post"}

    payment_paths = {
        path: methods
        for path, methods in paths.items()
        if "/payment" in path
    }
    assert set(payment_paths) == {
        "/projects/{project_id}/payment/create",
        "/projects/{project_id}/payment/capture",
        "/projects/{project_id}/payment",
    }
    assert set(payment_paths["/projects/{project_id}/payment/create"]) == {"post"}
    assert set(payment_paths["/projects/{project_id}/payment/capture"]) == {"post"}
    assert set(payment_paths["/projects/{project_id}/payment"]) == {"get"}

    forbidden = ("refund", "void", "authorize")
    assert not any(
        word in path.lower()
        for path in paths
        for word in forbidden
    )
