"""Security-focused regression tests for the Prompt 10 audit.

These tests pin the behaviours that must not regress: secret redaction,
CORS safety, login enumeration resistance, JWT validation, the
unauthenticated endpoint surface, project-level authorization (IDOR),
and safe uploads.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    create_access_token,
    hash_password,
    verify_login_password,
    verify_password,
)

from tests.helpers import (
    auth_headers,
    create_user,
    login_token,
    make_project,
    receipt_pdf_bytes,
    upload_evidence,
)


# ------------------------------------------------------------ settings


def test_settings_repr_hides_credentials_and_database_url():
    config = Settings(
        SECRET_KEY="secret-value-that-must-not-leak-0123456789",
        DATABASE_URL="sqlite:///secret-database-path.db",
        PAYPAL_CLIENT_ID="paypal-id-that-must-not-leak",
        PAYPAL_CLIENT_SECRET="paypal-secret-that-must-not-leak",
        _env_file=None,
    )

    rendered = repr(config)

    for secret in (
        "secret-value-that-must-not-leak-0123456789",
        "secret-database-path.db",
        "paypal-id-that-must-not-leak",
        "paypal-secret-that-must-not-leak",
    ):
        assert secret not in rendered


def test_cors_wildcard_with_credentials_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            SECRET_KEY="cors-test-secret",
            CORS_ORIGINS="*",
            CORS_ALLOW_CREDENTIALS=True,
            _env_file=None,
        )


def test_cors_wildcard_without_credentials_is_allowed():
    config = Settings(
        SECRET_KEY="cors-test-secret",
        CORS_ORIGINS=" http://a.example , * ",
        CORS_ALLOW_CREDENTIALS=False,
        _env_file=None,
    )

    assert config.cors_origins == ["http://a.example", "*"]


# ------------------------------------------------------ login timing


def test_unknown_account_password_check_never_succeeds():
    stored_hash = hash_password("right-password")

    assert verify_login_password("right-password", stored_hash) is True
    assert verify_login_password("wrong-password", stored_hash) is False
    assert verify_login_password("right-password", None) is False
    assert verify_login_password("", None) is False


def test_login_does_not_reveal_whether_an_account_exists(client, db):
    known = create_user(db, "audit-known", ROLE_CLIENT)

    unknown = client.post(
        "/auth/login",
        data={
            "username": "missing-account@example.com",
            "password": "some-password",
        },
    )
    wrong_password = client.post(
        "/auth/login",
        data={
            "username": known.email,
            "password": "definitely-wrong",
        },
    )

    assert unknown.status_code == 401
    assert wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()
    assert unknown.json()["error"]["code"] == "unauthorized"
    assert "Incorrect email or password." == unknown.json()["error"]["message"]


# --------------------------------------------------------- JWT checks


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_expired_token_is_rejected(client, db):
    user = create_user(db, "audit-expired", ROLE_CLIENT)
    token = create_access_token(user.id, expires_delta=timedelta(seconds=-1))

    response = client.get("/auth/me", headers=_bearer(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_token_with_wrong_signature_is_rejected(client, db):
    user = create_user(db, "audit-signature", ROLE_CLIENT)
    forged = jwt.encode(
        {
            "sub": str(user.id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "not-the-real-signing-key",
        algorithm="HS256",
    )

    response = client.get("/auth/me", headers=_bearer(forged))

    assert response.status_code == 401


def test_token_without_expiry_claim_is_rejected(client, db):
    user = create_user(db, "audit-no-exp", ROLE_CLIENT)
    token = jwt.encode(
        {"sub": str(user.id)},
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    response = client.get("/auth/me", headers=_bearer(token))

    assert response.status_code == 401


def test_unsigned_token_is_rejected(client, db):
    user = create_user(db, "audit-alg-none", ROLE_CLIENT)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        key="",
        algorithm="none",
    )

    response = client.get("/auth/me", headers=_bearer(token))

    assert response.status_code == 401


def test_token_for_deleted_user_is_rejected(client, db):
    user = create_user(db, "audit-deleted", ROLE_CLIENT)
    token = create_access_token(user.id)

    db.delete(user)
    db.commit()

    response = client.get("/auth/me", headers=_bearer(token))

    assert response.status_code == 401


# ------------------------------------------- unauthenticated surface


UNAUTHENTICATED_GET_PATHS = [
    "/auth/me",
    "/projects",
    "/projects/1",
    "/projects/1/status",
    "/projects/1/requirements",
    "/projects/1/requirements/1",
    "/projects/1/evidence",
    "/projects/1/evidence/1/download",
    "/projects/1/analysis",
    "/projects/1/analysis/history",
    "/projects/1/analysis/1",
    "/projects/1/reports",
    "/projects/1/reports/latest",
    "/projects/1/reports/1",
    "/reviews/pending",
    "/projects/1/reviews",
    "/projects/1/reviews/context",
    "/projects/1/reviews/1",
    "/projects/1/history",
    "/projects/1/paypal/status",
    "/projects/1/paypal/transactions",
    "/projects/1/paypal/transactions/CAPTURE-X",
    "/projects/1/payment",
]


@pytest.mark.parametrize("path", UNAUTHENTICATED_GET_PATHS)
def test_get_endpoints_require_authentication(client, path):
    response = client.get(path)

    assert response.status_code == 401, (path, response.text)
    assert response.json()["error"]["code"] == "unauthorized"


UNAUTHENTICATED_WRITES = [
    ("post", "/projects", {"json": {"title": "x", "freelancer_id": 1}}),
    (
        "post",
        "/projects/1/requirements",
        {"json": {"text": "Must exist", "category": "deliverable"}},
    ),
    ("post", "/projects/1/analysis", {}),
    ("post", "/projects/1/reports", {}),
    ("post", "/projects/1/reviews", {"json": {"decision": "verified"}}),
    (
        "post",
        "/projects/1/paypal/transactions/sync",
        {"json": {"transaction_id": "CAPTURE-X"}},
    ),
    ("post", "/projects/1/payment/create", {}),
    ("post", "/projects/1/payment/capture", {}),
    ("patch", "/projects/1", {"json": {"title": "Changed"}}),
    ("patch", "/projects/1/status", {"json": {"status": "in_progress"}}),
    (
        "patch",
        "/projects/1/requirements/1",
        {"json": {"text": "Changed text"}},
    ),
]


@pytest.mark.parametrize("method,path,kwargs", UNAUTHENTICATED_WRITES)
def test_write_endpoints_require_authentication(client, method, path, kwargs):
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401, (path, response.text)
    assert response.json()["error"]["code"] == "unauthorized"


def test_evidence_upload_requires_authentication(client):
    response = client.post(
        "/projects/1/evidence",
        files={"file": ("receipt.pdf", receipt_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 401


# ------------------------------------------------------- role matrix


def test_project_creation_is_client_only(client, db):
    freelancer = create_user(db, "audit-create-fl", ROLE_FREELANCER)
    reviewer = create_user(db, "audit-create-rev", ROLE_REVIEWER)
    payload = {"title": "Role check", "freelancer_id": freelancer.id}

    for user in (freelancer, reviewer):
        token = login_token(client, user.email)
        response = client.post(
            "/projects",
            json=payload,
            headers=auth_headers(token),
        )

        assert response.status_code == 403, user.role


def test_review_endpoints_are_reviewer_only(client, db):
    owner = create_user(db, "audit-review-owner", ROLE_CLIENT)
    freelancer = create_user(db, "audit-review-fl", ROLE_FREELANCER)
    project = make_project(db, "Review role", owner.id, freelancer.id)

    for user in (owner, freelancer):
        token = login_token(client, user.email)
        headers = auth_headers(token)

        assert client.get("/reviews/pending", headers=headers).status_code == 403
        assert (
            client.get(
                f"/projects/{project.id}/reviews", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/projects/{project.id}/reviews/context", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/projects/{project.id}/reviews",
                json={"decision": "verified"},
                headers=headers,
            ).status_code
            == 403
        )


def test_only_the_assigned_freelancer_can_upload_evidence(client, db):
    owner = create_user(db, "audit-upload-owner", ROLE_CLIENT)
    assigned = create_user(db, "audit-upload-assigned", ROLE_FREELANCER)
    other = create_user(db, "audit-upload-other", ROLE_FREELANCER)
    project = make_project(db, "Upload role", owner.id, assigned.id)

    owner_token = login_token(client, owner.email)
    other_token = login_token(client, other.email)

    assert upload_evidence(
        client, owner_token, project.id, receipt_pdf_bytes()
    ).status_code == 403
    assert upload_evidence(
        client, other_token, project.id, receipt_pdf_bytes()
    ).status_code == 403


# ------------------------------------------------------------- IDOR


def test_outsiders_cannot_reach_project_scoped_resources(client, db):
    owner = create_user(db, "audit-idor-owner", ROLE_CLIENT)
    assigned = create_user(db, "audit-idor-assigned", ROLE_FREELANCER)
    outsider_client = create_user(db, "audit-idor-client", ROLE_CLIENT)
    outsider_freelancer = create_user(
        db, "audit-idor-freelancer", ROLE_FREELANCER
    )
    project = make_project(db, "Private case", owner.id, assigned.id)

    for outsider in (outsider_client, outsider_freelancer):
        token = login_token(client, outsider.email)
        headers = auth_headers(token)
        project_path = f"/projects/{project.id}"

        reads = [
            project_path,
            f"{project_path}/status",
            f"{project_path}/requirements",
            f"{project_path}/requirements/1",
            f"{project_path}/evidence",
            f"{project_path}/analysis",
            f"{project_path}/analysis/history",
            f"{project_path}/analysis/1",
            f"{project_path}/reports",
            f"{project_path}/reports/latest",
            f"{project_path}/reports/1",
            f"{project_path}/history",
            f"{project_path}/paypal/status",
            f"{project_path}/paypal/transactions",
            f"{project_path}/paypal/transactions/CAPTURE-X",
        ]

        for path in reads:
            response = client.get(path, headers=headers)

            assert response.status_code == 403, (outsider.role, path)

        assert (
            client.post(
                f"{project_path}/analysis", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"{project_path}/reports", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.patch(
                project_path,
                json={"title": "Hijacked"},
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"{project_path}/status",
                json={"status": "in_progress"},
                headers=headers,
            ).status_code
            == 403
        )
        assert upload_evidence(
            client, token, project.id, receipt_pdf_bytes()
        ).status_code == 403


def test_outsider_client_cannot_write_requirements_or_sync_paypal(client, db):
    owner = create_user(db, "audit-write-owner", ROLE_CLIENT)
    freelancer = create_user(db, "audit-write-fl", ROLE_FREELANCER)
    outsider = create_user(db, "audit-write-outsider", ROLE_CLIENT)
    project = make_project(db, "Write guard", owner.id, freelancer.id)
    headers = auth_headers(login_token(client, outsider.email))

    assert (
        client.post(
            f"/projects/{project.id}/requirements",
            json={
                "text": "Injected requirement text",
                "category": "deliverable",
            },
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/projects/{project.id}/paypal/transactions/sync",
            json={"transaction_id": "CAPTURE-X"},
            headers=headers,
        ).status_code
        == 403
    )


# ------------------------------------------------- input and output


def test_validation_errors_do_not_echo_password(client):
    password = "é" * 40  # 80 UTF-8 bytes, above the bcrypt limit

    response = client.post(
        "/auth/register",
        json={
            "name": "Audit User",
            "email": "audit-echo@example.com",
            "password": password,
            "role": "client",
        },
    )

    assert response.status_code == 422
    assert password not in response.text
    assert "é" not in response.text
    assert all(
        "input" not in detail
        for detail in response.json()["error"]["details"]
    )


def test_unknown_login_password_is_not_echoed(client):
    secret = "super-secret-wrong-password-value"

    response = client.post(
        "/auth/login",
        data={"username": "nobody@example.com", "password": secret},
    )

    assert response.status_code == 401
    assert secret not in response.text


def test_user_responses_never_include_password_hashes(client, db):
    user = create_user(db, "audit-hash", ROLE_CLIENT)
    token = login_token(client, user.email)

    responses = [
        client.get("/auth/me", headers=auth_headers(token)),
        client.get("/projects", headers=auth_headers(token)),
    ]

    for response in responses:
        assert response.status_code == 200
        assert "password" not in response.text.lower()
        assert user.password_hash not in response.text

    schema_properties = client.get("/openapi.json").json()["components"][
        "schemas"
    ]["UserResponse"]["properties"]

    assert "password" not in schema_properties
    assert "password_hash" not in schema_properties


# ------------------------------------------------------------- uploads


def test_path_traversal_filename_is_neutralized(client, db):
    owner = create_user(db, "audit-file-owner", ROLE_CLIENT)
    freelancer = create_user(db, "audit-file-fl", ROLE_FREELANCER)
    project = make_project(db, "File safety", owner.id, freelancer.id)
    token = login_token(client, freelancer.email)
    data = receipt_pdf_bytes()

    response = upload_evidence(
        client,
        token,
        project.id,
        data,
        filename="../../evil/..\\windows\\payload.pdf",
    )

    assert response.status_code == 201, response.text
    assert response.json()["filename"] == "payload.pdf"
    assert "stored_path" not in response.json()

    download = client.get(
        f"/projects/{project.id}/evidence/{response.json()['id']}/download",
        headers=auth_headers(token),
    )

    assert download.status_code == 200
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "payload.pdf" in download.headers["content-disposition"]
    assert download.content == data

    uploaded_root = settings.upload_dir
    stored = [
        path
        for path in uploaded_root.rglob("*")
        if path.is_file()
    ]

    assert len(stored) == 1
    assert stored[0].resolve().is_relative_to(uploaded_root)


def test_password_hash_verification_matches_generated_hash():
    stored = hash_password("a-real-password")

    assert verify_password("a-real-password", stored) is True
    assert verify_password("not-the-password", stored) is False
