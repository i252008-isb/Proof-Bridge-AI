import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix="proofbridge-foundation-tests-"))
_TEST_UPLOAD_DIR = _TEST_DIR / "uploads"

os.environ["SECRET_KEY"] = "foundation-test-secret-key-32-bytes-min"
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DIR / 'test.db').as_posix()}"
os.environ["ACCESS_TOKEN_MINUTES"] = "5"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["UPLOAD_DIR"] = str(_TEST_UPLOAD_DIR)
os.environ["MAX_UPLOAD_BYTES"] = str(1024 * 1024)

# Tests must never call a paid external AI provider. Demo mode forces
# Person 3's deterministic mock LLM, embeddings, and vision providers.
os.environ["PROOFBRIDGE_DEMO_MODE"] = "true"
os.environ["PROOFBRIDGE_OCR_ENABLED"] = "false"
os.environ["PROOFBRIDGE_LLM_PROVIDER"] = "mock"
os.environ["PROOFBRIDGE_EMBEDDINGS_PROVIDER"] = "mock"
os.environ["PROOFBRIDGE_VISION_PROVIDER"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AnalysisResult,
    CaseStatusLog,
    Evidence,
    HumanReview,
    PayPalTransaction,
    Project,
    Report,
    Requirement,
    User,
)


@pytest.fixture(scope="session", autouse=True)
def database_schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean_database():
    yield

    session = SessionLocal()

    try:
        for model in (
            PayPalTransaction,
            HumanReview,
            Report,
            CaseStatusLog,
            AnalysisResult,
            Evidence,
            Requirement,
            Project,
            User,
        ):
            session.query(model).delete()

        session.commit()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_uploads():
    yield

    shutil.rmtree(_TEST_UPLOAD_DIR, ignore_errors=True)


@pytest.fixture()
def db():
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client
