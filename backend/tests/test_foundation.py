from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.config import BASE_DIR, Settings
from app.database import Base, engine, get_db, resolve_database_url
from app.main import app
from app.models import Project, User


EXPECTED_TABLES = {
    "users",
    "projects",
    "requirements",
    "evidence",
    "analysis_results",
    "case_status_log",
    "reports",
    "human_reviews",
    "paypal_transactions",
}

PROJECT_CHILD_RELATIONSHIPS = {
    "requirements",
    "evidence",
    "analysis_results",
    "status_logs",
    "reports",
    "human_reviews",
    "paypal_transactions",
}


# --------------------------------------------------------------- app wiring

def test_app_exposes_expected_routes():
    paths = set(app.openapi()["paths"])

    assert {
        "/",
        "/health",
        "/health/db",
        "/auth/register",
        "/auth/login",
        "/auth/me",
        "/projects",
        "/projects/{project_id}",
        "/projects/{project_id}/status",
        "/projects/{project_id}/requirements",
        "/projects/{project_id}/requirements/{requirement_id}",
        "/projects/{project_id}/agreement",
        "/projects/{project_id}/agreement/download",
        "/projects/{project_id}/evidence",
        "/projects/{project_id}/evidence/{evidence_id}/download",
        "/projects/{project_id}/analysis",
        "/projects/{project_id}/analysis/history",
        "/projects/{project_id}/analysis/{report_id}",
        "/projects/{project_id}/reports",
        "/projects/{project_id}/reports/latest",
        "/projects/{project_id}/reports/{report_id}",
        "/reviews/pending",
        "/projects/{project_id}/reviews",
        "/projects/{project_id}/reviews/context",
        "/projects/{project_id}/reviews/{review_id}",
        "/projects/{project_id}/history",
        "/projects/{project_id}/paypal/status",
        "/projects/{project_id}/paypal/transactions",
        "/projects/{project_id}/paypal/transactions/sync",
        "/projects/{project_id}/paypal/transactions/{transaction_id}",
        "/projects/{project_id}/payment/create",
        "/projects/{project_id}/payment/capture",
        "/projects/{project_id}/payment",
    } <= paths


def test_openapi_schema_is_generated(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health/db" in response.json()["paths"]


def test_root_returns_welcome_message(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "Welcome to ProofBridge AI"


# ---------------------------------------------------------------- health

def test_liveness_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "ProofBridge AI API"


def test_database_health_reports_ready(client):
    response = client.get("/health/db")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["missing_tables"] == []
    assert body["latency_ms"] >= 0


def test_database_health_reports_missing_tables(tmp_path):
    empty_engine = create_engine(
        f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    )
    empty_session = Session(empty_engine)

    def empty_db():
        yield empty_session

    app.dependency_overrides[get_db] = empty_db

    with TestClient(app) as client:
        response = client.get("/health/db")

    empty_session.close()
    empty_engine.dispose()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "ok"
    assert set(body["missing_tables"]) == EXPECTED_TABLES


class _BrokenSession:
    def execute(self, *args, **kwargs):
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("database is down")
        )


def test_database_health_reports_unavailable_database():
    def broken_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = broken_db

    with TestClient(app) as client:
        response = client.get("/health/db")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"


# ---------------------------------------------------------------- errors

class _ExplodingSession:
    def execute(self, *args, **kwargs):
        raise RuntimeError("unexpected failure")


def test_unhandled_errors_use_consistent_envelope():
    def exploding_db():
        yield _ExplodingSession()

    app.dependency_overrides[get_db] = exploding_db

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health/db")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred."
        }
    }


def test_not_found_uses_consistent_envelope(client):
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_validation_errors_use_consistent_envelope(client):
    response = client.post(
        "/auth/register",
        json={
            "name": "A",
            "email": "not-an-email",
            "password": "short",
            "role": "admin"
        }
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"] == "Request validation failed."
    assert body["error"]["details"]
    assert all("input" not in item for item in body["error"]["details"])


def test_unknown_fields_are_rejected(client):
    response = client.post(
        "/auth/register",
        json={
            "name": "Valid Name",
            "email": "extra@example.com",
            "password": "password123",
            "role": "client",
            "is_admin": True
        }
    )

    assert response.status_code == 422


# ------------------------------------------------------------------ CORS

def test_cors_preflight_allows_configured_origin(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET"
        }
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "http://localhost:5173"
    )


def test_cors_preflight_rejects_unknown_origin(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://unknown.example",
            "Access-Control-Request-Method": "GET"
        }
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


# ------------------------------------------------------------------ auth

def test_register_login_and_me_flow(client, db):
    register = client.post(
        "/auth/register",
        json={
            "name": "Foundation User",
            "email": "Foundation@Example.com",
            "password": "correct-horse-battery",
            "role": "client"
        }
    )

    assert register.status_code == 201
    created = register.json()
    assert created["email"] == "foundation@example.com"
    assert "password" not in created
    assert "password_hash" not in created

    login = client.post(
        "/auth/login",
        data={
            "username": "foundation@example.com",
            "password": "correct-horse-battery"
        }
    )

    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert me.status_code == 200
    assert me.json()["email"] == "foundation@example.com"


def test_login_rejects_wrong_password(client, db):
    client.post(
        "/auth/register",
        json={
            "name": "Wrong Password",
            "email": "wrong-password@example.com",
            "password": "correct-password",
            "role": "freelancer"
        }
    )

    response = client.post(
        "/auth/login",
        data={
            "username": "wrong-password@example.com",
            "password": "incorrect-password"
        }
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_password_byte_limit_is_enforced(client):
    response = client.post(
        "/auth/register",
        json={
            "name": "Byte Limit",
            "email": "byte-limit@example.com",
            "password": "é" * 40,
            "role": "client"
        }
    )

    assert response.status_code == 422


# --------------------------------------------------------------- settings

def test_settings_parse_cors_origins():
    settings = Settings(
        SECRET_KEY="test-secret",
        CORS_ORIGINS=" http://a.example , http://b.example ,",
        _env_file=None
    )

    assert settings.cors_origins == [
        "http://a.example",
        "http://b.example"
    ]


def test_settings_reject_non_positive_token_lifetime():
    with pytest.raises(ValidationError):
        Settings(
            SECRET_KEY="test-secret",
            ACCESS_TOKEN_MINUTES=0,
            _env_file=None
        )


def test_relative_sqlite_url_resolves_from_project_root():
    url = resolve_database_url("sqlite:///./proofbridge.db")

    assert Path(url.database) == (BASE_DIR / "proofbridge.db").resolve()


# ----------------------------------------------------------------- models

def test_all_nine_models_are_registered():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_project_relationships_cover_all_child_tables():
    relationships = sqlalchemy_inspect(Project).relationships

    assert {"freelancer", "client"} <= set(relationships.keys())
    assert PROJECT_CHILD_RELATIONSHIPS <= set(relationships.keys())

    for name in PROJECT_CHILD_RELATIONSHIPS:
        assert "delete-orphan" in str(relationships[name].cascade)


def test_sqlite_foreign_keys_are_enforced(db):
    db.add(Project(
        title="Orphan project",
        freelancer_id=999,
        client_id=998
    ))

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()


def test_create_all_preserves_existing_rows(db):
    db.add(User(
        name="Preserved User",
        email="preserved@example.com",
        password_hash="not-a-real-hash",
        role="client"
    ))
    db.commit()

    Base.metadata.create_all(bind=engine)

    assert db.query(User).filter(
        User.email == "preserved@example.com"
    ).count() == 1
