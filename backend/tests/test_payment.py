"""Tests for the new backend payment endpoints:
POST /projects/{id}/payment/create
POST /projects/{id}/payment/capture
GET  /projects/{id}/payment
"""

from decimal import Decimal
from unittest.mock import patch
import pytest

from app.models import PayPalTransaction, Project
from app.security import ROLE_CLIENT, ROLE_FREELANCER, ROLE_REVIEWER

from tests.helpers import (
    auth_headers,
    create_user,
    login_token,
    make_project,
)


@pytest.fixture
def project_setup(db):
    buyer = create_user(db, "buyer-payment", ROLE_CLIENT)
    seller = create_user(db, "seller-payment", ROLE_FREELANCER)
    outsider = create_user(db, "outsider-payment", ROLE_CLIENT)
    reviewer = create_user(db, "reviewer-payment", ROLE_REVIEWER)

    project = make_project(
        db,
        title="Product Purchase",
        client_id=buyer.id,
        freelancer_id=seller.id,
    )
    project.amount = "150.00"
    project.currency = "USD"
    db.commit()
    db.refresh(project)

    return {
        "buyer": buyer,
        "seller": seller,
        "outsider": outsider,
        "reviewer": reviewer,
        "project": project,
    }


def test_payment_create_by_buyer_success(client, project_setup):
    buyer = project_setup["buyer"]
    project = project_setup["project"]
    token = login_token(client, buyer.email)

    fake_result = {
        "order_id": "ORDER-999",
        "status": "CREATED",
        "payment_state": "PENDING_APPROVAL",
        "approval_link": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-999",
    }

    with patch(
        "app.routers.payment.create_payment",
        return_value=fake_result,
    ) as mock_create:
        response = client.post(
            f"/projects/{project.id}/payment/create",
            headers=auth_headers(token),
            json={"amount": "999.99"},  # Ignored: amount comes from DB only
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["order_id"] == "ORDER-999"
    assert data["approval_link"] == fake_result["approval_link"]
    assert data["payment_state"] == "PENDING_APPROVAL"

    # Verify amount passed to create_payment was from DB ("150.00"), not payload
    mock_create.assert_called_once_with(
        amount="150.00",
        currency="USD",
        case_id=str(project.id),
        mode="capture",
    )


def test_payment_create_non_owner_rejected(client, project_setup):
    seller = project_setup["seller"]
    outsider = project_setup["outsider"]
    reviewer = project_setup["reviewer"]
    project = project_setup["project"]

    for user in (seller, outsider, reviewer):
        token = login_token(client, user.email)
        res = client.post(
            f"/projects/{project.id}/payment/create",
            headers=auth_headers(token),
        )
        assert res.status_code == 403


def test_payment_create_fails_if_no_amount(client, project_setup, db):
    buyer = project_setup["buyer"]
    project = project_setup["project"]
    project.amount = None
    db.commit()

    token = login_token(client, buyer.email)
    res = client.post(
        f"/projects/{project.id}/payment/create",
        headers=auth_headers(token),
    )
    assert res.status_code == 400
    assert "no payment amount" in res.json()["error"]["message"].lower()


def test_payment_create_fails_if_already_paid(client, project_setup, db):
    buyer = project_setup["buyer"]
    project = project_setup["project"]

    tx = PayPalTransaction(
        project_id=project.id,
        paypal_transaction_id="CAP-ALREADY-PAID",
        amount=Decimal("150.00"),
        currency="USD",
        status="PAID",
        raw_data={"status": "COMPLETED"},
    )
    db.add(tx)
    db.commit()

    token = login_token(client, buyer.email)
    res = client.post(
        f"/projects/{project.id}/payment/create",
        headers=auth_headers(token),
    )
    assert res.status_code == 409
    assert "already paid" in res.json()["error"]["message"].lower()


def test_payment_capture_success_and_idempotence(client, project_setup, db):
    buyer = project_setup["buyer"]
    project = project_setup["project"]
    project.paypal_order_id = "ORDER-12345"
    db.commit()

    token = login_token(client, buyer.email)

    fake_capture = {
        "order_id": "ORDER-12345",
        "capture_id": "CAPTURE-777",
        "status": "COMPLETED",
        "payment_state": "PAID",
        "amount": "150.00",
        "currency": "USD",
        "case_id": str(project.id),
    }

    with patch(
        "app.routers.payment.capture_payment",
        return_value=fake_capture,
    ) as mock_capture:
        res1 = client.post(
            f"/projects/{project.id}/payment/capture",
            headers=auth_headers(token),
            json={"token": "ORDER-12345"},
        )
        assert res1.status_code == 200, res1.text
        data1 = res1.json()
        assert data1["status"] == "PAID"
        assert data1["capture_id"] == "CAPTURE-777"
        mock_capture.assert_called_once_with("ORDER-12345")

        # Second call: idempotent, does not call capture_payment again
        mock_capture.reset_mock()
        res2 = client.post(
            f"/projects/{project.id}/payment/capture",
            headers=auth_headers(token),
            json={"token": "ORDER-12345"},
        )
        assert res2.status_code == 200
        assert res2.json()["capture_id"] == "CAPTURE-777"
        mock_capture.assert_not_called()


def test_payment_capture_token_mismatch_rejected(client, project_setup, db):
    buyer = project_setup["buyer"]
    project = project_setup["project"]
    project.paypal_order_id = "ORDER-EXPECTED"
    db.commit()

    token = login_token(client, buyer.email)
    res = client.post(
        f"/projects/{project.id}/payment/capture",
        headers=auth_headers(token),
        json={"token": "ORDER-DIFFERENT"},
    )
    assert res.status_code == 400
    assert "does not match" in res.json()["error"]["message"].lower()


def test_payment_capture_amount_mismatch_rejected(client, project_setup, db):
    buyer = project_setup["buyer"]
    project = project_setup["project"]
    project.paypal_order_id = "ORDER-MISMATCH"
    db.commit()

    token = login_token(client, buyer.email)

    fake_capture = {
        "order_id": "ORDER-MISMATCH",
        "capture_id": "CAPTURE-BAD",
        "status": "COMPLETED",
        "payment_state": "PAID",
        "amount": "99.00",  # DB has 150.00
        "currency": "USD",
        "case_id": str(project.id),
    }

    with patch(
        "app.routers.payment.capture_payment",
        return_value=fake_capture,
    ):
        res = client.post(
            f"/projects/{project.id}/payment/capture",
            headers=auth_headers(token),
        )
        assert res.status_code == 422
        assert "amount does not match" in res.json()["error"]["message"].lower()


def test_payment_get_visibility(client, project_setup):
    buyer = project_setup["buyer"]
    seller = project_setup["seller"]
    reviewer = project_setup["reviewer"]
    outsider = project_setup["outsider"]
    project = project_setup["project"]

    for user in (buyer, seller, reviewer):
        token = login_token(client, user.email)
        res = client.get(
            f"/projects/{project.id}/payment",
            headers=auth_headers(token),
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["payment_state"] == "UNPAID"
        assert data["amount"] == "150.00"
        assert data["currency"] == "USD"

    # Outsider is rejected
    outsider_token = login_token(client, outsider.email)
    res = client.get(
        f"/projects/{project.id}/payment",
        headers=auth_headers(outsider_token),
    )
    assert res.status_code == 403


def test_payment_upstream_failure_returns_502(client, project_setup):
    buyer = project_setup["buyer"]
    project = project_setup["project"]
    token = login_token(client, buyer.email)

    with patch(
        "app.routers.payment.create_payment",
        side_effect=RuntimeError("PayPal connection timed out"),
    ):
        res = client.post(
            f"/projects/{project.id}/payment/create",
            headers=auth_headers(token),
        )
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "bad_gateway"


def test_money_movement_routes_forbidden_404(client, project_setup):
    buyer = project_setup["buyer"]
    project = project_setup["project"]
    token = login_token(client, buyer.email)

    forbidden_routes = [
        ("post", f"/projects/{project.id}/payment/refund"),
        ("post", f"/projects/{project.id}/payment/void"),
        ("post", f"/projects/{project.id}/payment/authorize"),
        ("post", f"/authorizations/{project.id}/capture"),
        ("post", f"/authorizations/{project.id}/void"),
    ]

    for method, path in forbidden_routes:
        res = getattr(client, method)(path, headers=auth_headers(token))
        assert res.status_code in (404, 405), f"Expected 404/405 for {path}, got {res.status_code}"
