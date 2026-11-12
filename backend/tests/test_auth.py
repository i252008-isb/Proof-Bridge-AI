from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.models import Project, User
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    create_access_token,
    hash_password,
    verify_password
)


PASSWORD = "correct-password-123"


def register_user(
    client,
    email="user@example.com",
    password=PASSWORD,
    role="client",
    name="Test User"
):
    return client.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": password,
            "role": role
        }
    )


def login_user(client, email, password=PASSWORD):
    return client.post(
        "/auth/login",
        data={
            "username": email,
            "password": password
        }
    )


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_user(db, email, role, password=PASSWORD):
    user = User(
        name="Direct User",
        email=email,
        password_hash=hash_password(password),
        role=role
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


# ----------------------------------------------------------- registration

def test_successful_registration_returns_safe_payload(client):
    response = register_user(
        client,
        email="  New.User@Example.com  "
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.user@example.com"
    assert body["name"] == "Test User"
    assert body["role"] == "client"
    assert "password" not in body
    assert "password_hash" not in body


def test_duplicate_registration_is_case_insensitive(client):
    assert register_user(
        client,
        email="duplicate@example.com"
    ).status_code == 201

    response = register_user(
        client,
        email="DUPLICATE@Example.com"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize("role", ["reviewer", "admin"])
def test_public_registration_cannot_grant_elevated_roles(client, role):
    response = register_user(
        client,
        email=f"{role}@example.com",
        role=role
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "password",
    [
        "short",
        "        ",
        "é" * 40
    ]
)
def test_registration_rejects_invalid_passwords(client, password):
    response = register_user(
        client,
        email="invalid-password@example.com",
        password=password
    )

    assert response.status_code == 422


# ------------------------------------------------------------------ login

def test_successful_login_returns_working_token(client):
    register_user(client, email="login@example.com")

    response = login_user(client, "LOGIN@Example.com")

    assert response.status_code == 200
    token = response.json()["access_token"]
    assert response.json()["token_type"] == "bearer"

    me = client.get("/auth/me", headers=auth_headers(token))

    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"
    assert me.json()["role"] == "client"


def test_incorrect_password_and_unknown_email_share_same_error(client):
    register_user(client, email="known@example.com")

    wrong_password = login_user(
        client,
        "known@example.com",
        password="incorrect-password"
    )
    unknown_email = login_user(
        client,
        "unknown@example.com",
        password=PASSWORD
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert (
        wrong_password.json()["error"]["message"]
        == unknown_email.json()["error"]["message"]
    )
    assert wrong_password.json()["error"]["code"] == "unauthorized"


# ------------------------------------------------------------- token rules

def test_protected_endpoint_requires_token(client):
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].lower().startswith("bearer")


def test_malformed_token_is_rejected(client):
    response = client.get(
        "/auth/me",
        headers=auth_headers("not-a-real-token")
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_token_signed_with_wrong_secret_is_rejected(client, db):
    user = create_user(db, "wrong-signature@example.com", ROLE_CLIENT)
    now = datetime.now(timezone.utc)

    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + timedelta(minutes=5)
        },
        settings.SECRET_KEY + "-wrong",
        algorithm="HS256"
    )

    response = client.get("/auth/me", headers=auth_headers(token))

    assert response.status_code == 401


def test_expired_token_is_rejected(client, db):
    user = create_user(db, "expired@example.com", ROLE_CLIENT)

    token = create_access_token(
        user.id,
        expires_delta=timedelta(minutes=-5)
    )

    response = client.get("/auth/me", headers=auth_headers(token))

    assert response.status_code == 401
    assert response.json()["error"]["message"] == (
        "Invalid or expired authentication token."
    )


def test_token_without_required_claims_is_rejected(client, db):
    user = create_user(db, "claims@example.com", ROLE_CLIENT)

    token = jwt.encode(
        {"sub": str(user.id)},
        settings.SECRET_KEY,
        algorithm="HS256"
    )

    response = client.get("/auth/me", headers=auth_headers(token))

    assert response.status_code == 401


def test_token_for_missing_user_is_rejected(client):
    token = create_access_token(2_000_000)

    response = client.get("/auth/me", headers=auth_headers(token))

    assert response.status_code == 401


# ----------------------------------------------------------------- logout

def test_logout_requires_authentication(client):
    response = client.post("/auth/logout")

    assert response.status_code == 401


def test_logout_returns_message_for_stateless_tokens(client):
    register_user(client, email="logout@example.com")
    token = login_user(
        client,
        "logout@example.com"
    ).json()["access_token"]

    response = client.post("/auth/logout", headers=auth_headers(token))

    assert response.status_code == 200
    assert "Discard the access token" in response.json()["message"]

    still_valid = client.get("/auth/me", headers=auth_headers(token))
    assert still_valid.status_code == 200


# --------------------------------------------------------- password hashing

def test_bcrypt_hashing_and_verification():
    hashed = hash_password(PASSWORD)

    assert hashed != PASSWORD
    assert hashed.startswith(("$2a$", "$2b$", "$2y$"))
    assert verify_password(PASSWORD, hashed)
    assert not verify_password("wrong-password", hashed)
    assert not verify_password("é" * 40, hashed)

    with pytest.raises(ValueError):
        hash_password("é" * 40)


# ------------------------------------------------------------- role checks

def test_project_listing_is_scoped_by_role(client, db):
    freelancer = create_user(
        db,
        "role-freelancer@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(
        db,
        "role-reviewer@example.com",
        ROLE_REVIEWER
    )

    freelancer_token = login_user(
        client,
        freelancer.email
    ).json()["access_token"]
    reviewer_token = login_user(
        client,
        reviewer.email
    ).json()["access_token"]

    freelancer_list = client.get(
        "/projects",
        headers=auth_headers(freelancer_token)
    )
    reviewer_list = client.get(
        "/projects",
        headers=auth_headers(reviewer_token)
    )

    assert freelancer_list.status_code == 200
    assert freelancer_list.json() == []
    assert reviewer_list.status_code == 200


def test_project_access_is_limited_to_participants_and_reviewers(client, db):
    freelancer = create_user(
        db,
        "owner-freelancer@example.com",
        ROLE_FREELANCER
    )
    owner = create_user(
        db,
        "owner-client@example.com",
        ROLE_CLIENT
    )
    outsider = create_user(
        db,
        "outsider@example.com",
        ROLE_CLIENT
    )
    reviewer = create_user(
        db,
        "reviewer@example.com",
        ROLE_REVIEWER
    )

    project = Project(
        title="Owned project",
        freelancer_id=freelancer.id,
        client_id=owner.id
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    owner_token = login_user(client, owner.email).json()["access_token"]
    freelancer_token = login_user(
        client,
        freelancer.email
    ).json()["access_token"]
    outsider_token = login_user(client, outsider.email).json()["access_token"]
    reviewer_token = login_user(client, reviewer.email).json()["access_token"]

    assert client.get(
        f"/projects/{project.id}",
        headers=auth_headers(owner_token)
    ).status_code == 200

    assert client.get(
        f"/projects/{project.id}",
        headers=auth_headers(freelancer_token)
    ).status_code == 200

    assert client.get(
        f"/projects/{project.id}",
        headers=auth_headers(reviewer_token)
    ).status_code == 200

    forbidden = client.get(
        f"/projects/{project.id}",
        headers=auth_headers(outsider_token)
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


def test_missing_project_returns_not_found(client, db):
    user = create_user(db, "missing-project@example.com", ROLE_CLIENT)
    token = login_user(client, user.email).json()["access_token"]

    response = client.get(
        "/projects/999999",
        headers=auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
