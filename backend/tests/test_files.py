import io
import re
import zipfile
from uuid import uuid4

import pytest

from app.config import settings
from app.models import Evidence, Project, User
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    hash_password
)


PASSWORD = "correct-password-123"

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP_BYTES = (
    b"RIFF"
    + (20).to_bytes(4, "little")
    + b"WEBP"
    + b"VP8 "
    + b"\x00" * 12
)
GIF_BYTES = b"GIF89a" + b"\x00" * 32

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document"
)


def docx_bytes():
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")

    return buffer.getvalue()


def zip_without_document():
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "not a document")

    return buffer.getvalue()


DOCX_BYTES = docx_bytes()


def unique_email(prefix):
    return f"{prefix}-{uuid4().hex}@example.com"


def create_user(db, prefix, role):
    user = User(
        name="File Test User",
        email=unique_email(prefix),
        password_hash=hash_password(PASSWORD),
        role=role
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def login_token(client, email):
    response = client.post(
        "/auth/login",
        data={
            "username": email,
            "password": PASSWORD
        }
    )

    assert response.status_code == 200, response.text

    return response.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def make_project(db, title, client_id, freelancer_id, status="created"):
    project = Project(
        title=title,
        description="Project description",
        status=status,
        client_id=client_id,
        freelancer_id=freelancer_id
    )

    db.add(project)
    db.commit()
    db.refresh(project)

    return project


def make_evidence(
    db,
    project_id,
    uploaded_by,
    filename,
    stored_path,
    mime_type=None,
    extracted_text=None
):
    evidence = Evidence(
        project_id=project_id,
        uploaded_by=uploaded_by,
        filename=filename,
        stored_path=stored_path,
        mime_type=mime_type,
        extracted_text=extracted_text
    )

    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    return evidence


def upload_agreement(
    client,
    token,
    project_id,
    data,
    filename="agreement.pdf",
    content_type="application/pdf"
):
    headers = auth_headers(token) if token else {}

    return client.post(
        f"/projects/{project_id}/agreement",
        files={"file": (filename, data, content_type)},
        headers=headers
    )


def upload_evidence(
    client,
    token,
    project_id,
    data,
    filename="evidence.png",
    content_type="application/octet-stream"
):
    headers = auth_headers(token) if token else {}

    return client.post(
        f"/projects/{project_id}/evidence",
        files={"file": (filename, data, content_type)},
        headers=headers
    )


def assert_error(response, status_code, code):
    assert response.status_code == status_code, response.text
    assert response.json()["error"]["code"] == code


# ------------------------------------------------------------- agreements

def test_client_owner_can_upload_and_participants_can_download_agreement(
    client,
    db
):
    owner = create_user(db, "agreement-owner", ROLE_CLIENT)
    freelancer = create_user(db, "agreement-freelancer", ROLE_FREELANCER)
    reviewer = create_user(db, "agreement-reviewer", ROLE_REVIEWER)
    outsider_client = create_user(db, "agreement-outsider", ROLE_CLIENT)
    outsider_freelancer = create_user(
        db,
        "agreement-outsider-free",
        ROLE_FREELANCER
    )
    project = make_project(db, "Agreement project", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    response = upload_agreement(
        client,
        token,
        project.id,
        PDF_BYTES,
        filename="..\\agreements/My Agreement (final).pdf",
        content_type="text/plain"
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body == {
        "project_id": project.id,
        "agreement_name": "My Agreement (final).pdf",
        "mime_type": "application/pdf",
        "size_bytes": len(PDF_BYTES),
        "replaced_existing": False
    }
    assert "stored_path" not in body
    assert "agreement_path" not in body

    db.expire_all()
    stored = db.get(Project, project.id)
    assert stored.agreement_name == "My Agreement (final).pdf"
    assert stored.agreement_path.startswith(f"agreements/{project.id}/")
    assert stored.agreement_path.endswith(".pdf")
    assert ".." not in stored.agreement_path
    assert re.fullmatch(
        r"agreements/\d+/[0-9a-f]{32}\.pdf",
        stored.agreement_path
    )

    stored_file = settings.upload_dir / stored.agreement_path
    assert stored_file.read_bytes() == PDF_BYTES

    for user in (owner, freelancer, reviewer):
        user_token = login_token(client, user.email)
        download = client.get(
            f"/projects/{project.id}/agreement/download",
            headers=auth_headers(user_token)
        )

        assert download.status_code == 200
        assert download.content == PDF_BYTES
        assert download.headers["x-content-type-options"] == "nosniff"
        disposition = download.headers["content-disposition"].lower()
        assert "attachment" in disposition
        assert ".pdf" in disposition

    for user in (outsider_client, outsider_freelancer):
        user_token = login_token(client, user.email)
        download = client.get(
            f"/projects/{project.id}/agreement/download",
            headers=auth_headers(user_token)
        )

        assert download.status_code == 403


def test_agreement_replacement_removes_previous_file(client, db):
    owner = create_user(db, "replace-owner", ROLE_CLIENT)
    freelancer = create_user(db, "replace-freelancer", ROLE_FREELANCER)
    project = make_project(db, "Replace project", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    first = upload_agreement(client, token, project.id, PDF_BYTES)
    assert first.status_code == 201

    db.expire_all()
    old_path = db.get(Project, project.id).agreement_path
    old_file = settings.upload_dir / old_path
    assert old_file.is_file()

    second = upload_agreement(
        client,
        token,
        project.id,
        DOCX_BYTES,
        filename="agreement.pdf",
        content_type="application/pdf"
    )

    assert second.status_code == 201, second.text
    body = second.json()
    assert body["agreement_name"] == "agreement.docx"
    assert body["mime_type"] == DOCX_MIME
    assert body["replaced_existing"] is True

    db.expire_all()
    new_path = db.get(Project, project.id).agreement_path
    assert new_path != old_path
    assert old_file.exists() is False
    assert (settings.upload_dir / new_path).read_bytes() == DOCX_BYTES

    download = client.get(
        f"/projects/{project.id}/agreement/download",
        headers=auth_headers(token)
    )

    assert download.status_code == 200
    assert download.content == DOCX_BYTES
    assert download.headers["content-type"] == DOCX_MIME


def test_agreement_upload_requires_client_owner_and_mutable_project(
    client,
    db
):
    owner = create_user(db, "agreement-auth-owner", ROLE_CLIENT)
    other_client = create_user(db, "agreement-auth-client", ROLE_CLIENT)
    freelancer = create_user(db, "agreement-auth-free", ROLE_FREELANCER)
    reviewer = create_user(db, "agreement-auth-reviewer", ROLE_REVIEWER)
    project = make_project(db, "Agreement auth", owner.id, freelancer.id)
    finished = make_project(
        db,
        "Finished agreement",
        owner.id,
        freelancer.id,
        status="completed"
    )

    for user in (other_client, freelancer, reviewer):
        token = login_token(client, user.email)
        response = upload_agreement(client, token, project.id, PDF_BYTES)
        assert response.status_code == 403

    owner_token = login_token(client, owner.email)

    assert upload_agreement(
        client,
        owner_token,
        project.id,
        PDF_BYTES
    ).status_code == 201
    assert upload_agreement(
        client,
        owner_token,
        999999,
        PDF_BYTES
    ).status_code == 404
    assert upload_agreement(
        client,
        owner_token,
        finished.id,
        PDF_BYTES
    ).status_code == 409


@pytest.mark.parametrize(
    "data, filename, content_type, expected_status, error_code",
    [
        (b"", "empty.pdf", "application/pdf", 400, "bad_request"),
        (GIF_BYTES, "fake.pdf", "application/pdf", 415,
         "unsupported_media_type"),
        (zip_without_document(), "archive.docx", DOCX_MIME, 415,
         "unsupported_media_type"),
        (
            b"%PDF" + b"0" * settings.MAX_UPLOAD_BYTES,
            "large.pdf",
            "application/pdf",
            413,
            "payload_too_large"
        ),
    ]
)
def test_agreement_upload_rejects_invalid_files(
    client,
    db,
    data,
    filename,
    content_type,
    expected_status,
    error_code
):
    owner = create_user(db, "agreement-invalid-owner", ROLE_CLIENT)
    freelancer = create_user(db, "agreement-invalid-free", ROLE_FREELANCER)
    project = make_project(db, "Invalid agreement", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    response = upload_agreement(
        client,
        token,
        project.id,
        data,
        filename=filename,
        content_type=content_type
    )

    assert_error(response, expected_status, error_code)
    assert not settings.upload_dir.exists() or not any(
        path.is_file() for path in settings.upload_dir.rglob("*")
    )


def test_agreement_upload_missing_file_returns_validation_error(client, db):
    owner = create_user(db, "agreement-missing-owner", ROLE_CLIENT)
    freelancer = create_user(db, "agreement-missing-free", ROLE_FREELANCER)
    project = make_project(db, "Missing file", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    response = client.post(
        f"/projects/{project.id}/agreement",
        headers=auth_headers(token)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_agreement_download_before_upload_returns_not_found(client, db):
    owner = create_user(db, "agreement-empty-owner", ROLE_CLIENT)
    freelancer = create_user(db, "agreement-empty-free", ROLE_FREELANCER)
    outsider = create_user(db, "agreement-empty-outsider", ROLE_CLIENT)
    project = make_project(db, "Empty agreement", owner.id, freelancer.id)

    owner_token = login_token(client, owner.email)
    freelancer_token = login_token(client, freelancer.email)
    outsider_token = login_token(client, outsider.email)

    for token in (owner_token, freelancer_token):
        response = client.get(
            f"/projects/{project.id}/agreement/download",
            headers=auth_headers(token)
        )
        assert response.status_code == 404

    response = client.get(
        f"/projects/{project.id}/agreement/download",
        headers=auth_headers(outsider_token)
    )
    assert response.status_code == 403


def test_agreement_download_rejects_unsafe_stored_paths(client, db):
    owner = create_user(db, "agreement-path-owner", ROLE_CLIENT)
    freelancer = create_user(db, "agreement-path-free", ROLE_FREELANCER)
    project = make_project(db, "Unsafe agreement", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    outside = settings.upload_dir.parent / "outside-agreement.pdf"
    outside.write_bytes(PDF_BYTES)

    try:
        project.agreement_path = "../outside-agreement.pdf"
        project.agreement_name = "outside-agreement.pdf"
        db.commit()

        response = client.get(
            f"/projects/{project.id}/agreement/download",
            headers=auth_headers(token)
        )
        assert response.status_code == 404
        assert response.content != PDF_BYTES

        project.agreement_path = outside.resolve().as_posix()
        db.commit()

        response = client.get(
            f"/projects/{project.id}/agreement/download",
            headers=auth_headers(token)
        )
        assert response.status_code == 404

        project.agreement_path = f"agreements/{project.id}/missing.pdf"
        db.commit()

        response = client.get(
            f"/projects/{project.id}/agreement/download",
            headers=auth_headers(token)
        )
        assert response.status_code == 404
    finally:
        outside.unlink(missing_ok=True)


# --------------------------------------------------------------- evidence

def test_assigned_freelancer_uploads_evidence_with_metadata(client, db):
    owner = create_user(db, "evidence-owner", ROLE_CLIENT)
    freelancer = create_user(db, "evidence-freelancer", ROLE_FREELANCER)
    project = make_project(db, "Evidence project", owner.id, freelancer.id)
    token = login_token(client, freelancer.email)

    response = upload_evidence(
        client,
        token,
        project.id,
        PNG_BYTES,
        filename="../../Screenshot (1).PNG",
        content_type="application/pdf"
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "project_id",
        "uploaded_by",
        "filename",
        "mime_type",
        "created_at"
    }
    assert body["project_id"] == project.id
    assert body["uploaded_by"] == freelancer.id
    assert body["filename"] == "Screenshot (1).png"
    assert body["mime_type"] == "image/png"
    assert "stored_path" not in body
    assert "extracted_text" not in body

    db.expire_all()
    stored = db.get(Evidence, body["id"])
    assert stored.filename == "Screenshot (1).png"
    assert stored.mime_type == "image/png"
    assert stored.extracted_text is None
    assert stored.stored_path.startswith(f"evidence/{project.id}/")
    assert stored.stored_path.endswith(".png")
    assert ".." not in stored.stored_path
    assert re.fullmatch(
        r"evidence/\d+/[0-9a-f]{32}\.png",
        stored.stored_path
    )
    assert (settings.upload_dir / stored.stored_path).read_bytes() == PNG_BYTES


def test_evidence_listing_and_download_are_access_controlled(client, db):
    client_a = create_user(db, "list-evidence-client-a", ROLE_CLIENT)
    client_b = create_user(db, "list-evidence-client-b", ROLE_CLIENT)
    freelancer_a = create_user(db, "list-evidence-free-a", ROLE_FREELANCER)
    freelancer_b = create_user(db, "list-evidence-free-b", ROLE_FREELANCER)
    reviewer = create_user(db, "list-evidence-reviewer", ROLE_REVIEWER)

    project_a = make_project(
        db,
        "Evidence project A",
        client_a.id,
        freelancer_a.id
    )
    project_b = make_project(
        db,
        "Evidence project B",
        client_b.id,
        freelancer_b.id
    )
    token_a = login_token(client, freelancer_a.email)

    first = upload_evidence(
        client,
        token_a,
        project_a.id,
        PNG_BYTES,
        filename="first.png",
        content_type="image/png"
    )
    second = upload_evidence(
        client,
        token_a,
        project_a.id,
        PDF_BYTES,
        filename="second.pdf",
        content_type="application/pdf"
    )

    assert first.status_code == 201
    assert second.status_code == 201
    first_id = first.json()["id"]
    second_id = second.json()["id"]

    def list_for(user):
        token = login_token(client, user.email)
        return client.get(
            f"/projects/{project_a.id}/evidence",
            headers=auth_headers(token)
        )

    for user in (client_a, freelancer_a, reviewer):
        response = list_for(user)
        assert response.status_code == 200
        body = response.json()
        assert [item["id"] for item in body] == [first_id, second_id]

        for item in body:
            assert set(item) == {
                "id",
                "project_id",
                "uploaded_by",
                "filename",
                "mime_type",
                "created_at"
            }
            assert "stored_path" not in item
            assert "extracted_text" not in item

    for user in (client_b, freelancer_b):
        assert list_for(user).status_code == 403

    missing = client.get(
        "/projects/999999/evidence",
        headers=auth_headers(login_token(client, client_a.email))
    )
    assert missing.status_code == 404

    def download(user, project_id, evidence_id):
        token = login_token(client, user.email)
        return client.get(
            f"/projects/{project_id}/evidence/{evidence_id}/download",
            headers=auth_headers(token)
        )

    for user in (client_a, freelancer_a, reviewer):
        response = download(user, project_a.id, first_id)
        assert response.status_code == 200
        assert response.content == PNG_BYTES

    assert download(client_b, project_a.id, first_id).status_code == 403
    assert download(
        client_b,
        project_b.id,
        first_id
    ).status_code == 404
    assert download(
        client_a,
        project_a.id,
        999999
    ).status_code == 404


def test_evidence_upload_is_restricted_to_assigned_freelancer(client, db):
    owner = create_user(db, "upload-evidence-owner", ROLE_CLIENT)
    assigned = create_user(db, "upload-evidence-assigned", ROLE_FREELANCER)
    other_freelancer = create_user(
        db,
        "upload-evidence-other",
        ROLE_FREELANCER
    )
    reviewer = create_user(db, "upload-evidence-reviewer", ROLE_REVIEWER)

    project = make_project(db, "Upload evidence", owner.id, assigned.id)
    finished = make_project(
        db,
        "Finished evidence",
        owner.id,
        assigned.id,
        status="cancelled"
    )

    for user in (owner, reviewer, other_freelancer):
        token = login_token(client, user.email)
        response = upload_evidence(client, token, project.id, PNG_BYTES)
        assert response.status_code == 403

    assigned_token = login_token(client, assigned.email)
    assert upload_evidence(
        client,
        assigned_token,
        project.id,
        PNG_BYTES
    ).status_code == 201
    assert upload_evidence(
        client,
        assigned_token,
        999999,
        PNG_BYTES
    ).status_code == 404
    assert upload_evidence(
        client,
        assigned_token,
        finished.id,
        PNG_BYTES
    ).status_code == 409


@pytest.mark.parametrize(
    "data, filename, content_type, expected_status, error_code",
    [
        (b"", "empty.png", "image/png", 400, "bad_request"),
        (GIF_BYTES, "fake.png", "image/png", 415,
         "unsupported_media_type"),
        (zip_without_document(), "archive.docx", DOCX_MIME, 415,
         "unsupported_media_type"),
        (
            b"%PDF" + b"0" * settings.MAX_UPLOAD_BYTES,
            "large.pdf",
            "application/pdf",
            413,
            "payload_too_large"
        ),
    ]
)
def test_evidence_upload_rejects_invalid_files(
    client,
    db,
    data,
    filename,
    content_type,
    expected_status,
    error_code
):
    owner = create_user(db, "evidence-invalid-owner", ROLE_CLIENT)
    freelancer = create_user(db, "evidence-invalid-free", ROLE_FREELANCER)
    project = make_project(db, "Invalid evidence", owner.id, freelancer.id)
    token = login_token(client, freelancer.email)

    response = upload_evidence(
        client,
        token,
        project.id,
        data,
        filename=filename,
        content_type=content_type
    )

    assert_error(response, expected_status, error_code)
    assert db.query(Evidence).count() == 0
    assert not settings.upload_dir.exists() or not any(
        path.is_file() for path in settings.upload_dir.rglob("*")
    )


def test_evidence_upload_missing_file_returns_validation_error(client, db):
    owner = create_user(db, "evidence-missing-owner", ROLE_CLIENT)
    freelancer = create_user(db, "evidence-missing-free", ROLE_FREELANCER)
    project = make_project(db, "Missing evidence", owner.id, freelancer.id)
    token = login_token(client, freelancer.email)

    response = client.post(
        f"/projects/{project.id}/evidence",
        headers=auth_headers(token)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "data, expected_extension, expected_mime",
    [
        (PDF_BYTES, ".pdf", "application/pdf"),
        (DOCX_BYTES, ".docx", DOCX_MIME),
        (PNG_BYTES, ".png", "image/png"),
        (JPEG_BYTES, ".jpg", "image/jpeg"),
        (WEBP_BYTES, ".webp", "image/webp"),
    ]
)
def test_supported_formats_are_detected_from_content(
    client,
    db,
    data,
    expected_extension,
    expected_mime
):
    owner = create_user(db, "detect-owner", ROLE_CLIENT)
    freelancer = create_user(db, "detect-freelancer", ROLE_FREELANCER)
    project = make_project(db, "Detection project", owner.id, freelancer.id)
    token = login_token(client, freelancer.email)

    response = upload_evidence(
        client,
        token,
        project.id,
        data,
        filename="spoofed.txt",
        content_type="text/plain"
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == f"spoofed{expected_extension}"
    assert body["mime_type"] == expected_mime


def test_evidence_download_rejects_unsafe_or_missing_stored_paths(
    client,
    db
):
    owner = create_user(db, "evidence-path-owner", ROLE_CLIENT)
    freelancer = create_user(db, "evidence-path-free", ROLE_FREELANCER)
    project = make_project(db, "Evidence paths", owner.id, freelancer.id)
    token = login_token(client, freelancer.email)

    valid = upload_evidence(
        client,
        token,
        project.id,
        PNG_BYTES,
        filename="original.png",
        content_type="image/png"
    )
    assert valid.status_code == 201
    valid_id = valid.json()["id"]

    valid_record = db.get(Evidence, valid_id)
    valid_record.filename = "../../unsafe-name.png"
    db.commit()

    response = client.get(
        f"/projects/{project.id}/evidence/{valid_id}/download",
        headers=auth_headers(token)
    )
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "unsafe-name.png" in disposition
    assert ".." not in disposition

    outside = settings.upload_dir.parent / "outside-evidence.png"
    outside.write_bytes(PNG_BYTES)

    try:
        relative_escape = make_evidence(
            db,
            project.id,
            freelancer.id,
            "escape.png",
            "../outside-evidence.png",
            "image/png"
        )
        absolute_escape = make_evidence(
            db,
            project.id,
            freelancer.id,
            "absolute.png",
            outside.resolve().as_posix(),
            "image/png"
        )
        missing = make_evidence(
            db,
            project.id,
            freelancer.id,
            "missing.png",
            f"evidence/{project.id}/missing.png",
            "image/png"
        )

        for evidence in (relative_escape, absolute_escape, missing):
            result = client.get(
                f"/projects/{project.id}/evidence/{evidence.id}/download",
                headers=auth_headers(token)
            )
            assert result.status_code == 404
            assert result.content != PNG_BYTES
    finally:
        outside.unlink(missing_ok=True)


def test_existing_evidence_records_are_preserved(client, db):
    owner = create_user(db, "preserve-owner", ROLE_CLIENT)
    freelancer = create_user(db, "preserve-freelancer", ROLE_FREELANCER)
    project = make_project(db, "Preserve evidence", owner.id, freelancer.id)
    token = login_token(client, freelancer.email)

    legacy_path = f"evidence/{project.id}/legacy.txt"
    legacy_file = settings.upload_dir / legacy_path
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_bytes(b"legacy evidence content")

    legacy = make_evidence(
        db,
        project.id,
        freelancer.id,
        "legacy.txt",
        legacy_path,
        "text/plain",
        "legacy extracted text"
    )

    uploaded = upload_evidence(
        client,
        token,
        project.id,
        PNG_BYTES,
        filename="new.png",
        content_type="image/png"
    )
    assert uploaded.status_code == 201

    response = client.get(
        f"/projects/{project.id}/evidence",
        headers=auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [legacy.id, uploaded.json()["id"]]

    legacy_body = body[0]
    assert legacy_body["filename"] == "legacy.txt"
    assert legacy_body["mime_type"] == "text/plain"
    assert "extracted_text" not in legacy_body

    db.expire_all()
    stored = db.get(Evidence, legacy.id)
    assert stored.stored_path == legacy_path
    assert stored.extracted_text == "legacy extracted text"

    download = client.get(
        f"/projects/{project.id}/evidence/{legacy.id}/download",
        headers=auth_headers(token)
    )
    assert download.status_code == 200
    assert download.content == b"legacy evidence content"
    assert download.headers["content-type"].startswith("text/plain")


def test_file_endpoints_require_authentication(client, db):
    owner = create_user(db, "auth-files-owner", ROLE_CLIENT)
    freelancer = create_user(db, "auth-files-free", ROLE_FREELANCER)
    project = make_project(db, "Auth files", owner.id, freelancer.id)

    assert client.get(
        f"/projects/{project.id}/agreement/download"
    ).status_code == 401
    assert client.post(
        f"/projects/{project.id}/agreement",
        files={"file": ("agreement.pdf", PDF_BYTES, "application/pdf")}
    ).status_code == 401
    assert client.get(
        f"/projects/{project.id}/evidence"
    ).status_code == 401
    assert client.get(
        f"/projects/{project.id}/evidence/1/download"
    ).status_code == 401
    assert client.post(
        f"/projects/{project.id}/evidence",
        files={"file": ("evidence.png", PNG_BYTES, "image/png")}
    ).status_code == 401
