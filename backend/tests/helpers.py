from uuid import uuid4

import pymupdf

from app.models import Project, Requirement, User
from app.security import hash_password


PASSWORD = "correct-password-123"


def unique_email(prefix):
    return f"{prefix}-{uuid4().hex}@example.com"


def create_user(db, prefix, role):
    user = User(
        name="Prompt 9 Test User",
        email=unique_email(prefix),
        password_hash=hash_password(PASSWORD),
        role=role,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def login_token(client, email):
    response = client.post(
        "/auth/login",
        data={"username": email, "password": PASSWORD},
    )

    assert response.status_code == 200, response.text

    return response.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def make_project(db, title, client_id, freelancer_id, status="created"):
    project = Project(
        title=title,
        description=(
            "The delivered work is incomplete and does not match the "
            "agreed requirements."
        ),
        status=status,
        client_id=client_id,
        freelancer_id=freelancer_id,
    )

    db.add(project)
    db.commit()
    db.refresh(project)

    return project


def make_requirement(db, project_id, text):
    requirement = Requirement(
        project_id=project_id,
        text=text,
        category="deliverable",
    )

    db.add(requirement)
    db.commit()
    db.refresh(requirement)

    return requirement


def receipt_pdf_bytes():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "RECEIPT")
    page.insert_text((72, 92), "Order #ORD-1234")
    page.insert_text((72, 112), "Date: 2026-11-01")
    page.insert_text((72, 132), "Total: $49.99")
    page.insert_text((72, 152), "Item: Responsive landing page")
    data = document.tobytes()
    document.close()

    return data


def upload_evidence(
    client,
    token,
    project_id,
    data,
    filename="receipt.pdf",
    content_type="application/pdf",
):
    return client.post(
        f"/projects/{project_id}/evidence",
        files={"file": (filename, data, content_type)},
        headers=auth_headers(token),
    )


def run_analysis(client, token, project_id, force=False):
    suffix = "?force=true" if force else ""
    return client.post(
        f"/projects/{project_id}/analysis{suffix}",
        headers=auth_headers(token),
    )


def change_status(client, token, project_id, new_status, note=None):
    payload = {"status": new_status}

    if note is not None:
        payload["note"] = note

    return client.patch(
        f"/projects/{project_id}/status",
        json=payload,
        headers=auth_headers(token),
    )


def generate_report(client, token, project_id, analysis_report_id=None):
    suffix = (
        f"?analysis_report_id={analysis_report_id}"
        if analysis_report_id is not None
        else ""
    )
    return client.post(
        f"/projects/{project_id}/reports{suffix}",
        headers=auth_headers(token),
    )


def analysed_project(client, db, title="Deliverable verification"):
    """Create a project with one requirement, one evidence file, analysis."""
    from app.security import ROLE_CLIENT, ROLE_FREELANCER

    owner = create_user(db, "p9-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-freelancer", ROLE_FREELANCER)
    project = make_project(db, title, owner.id, freelancer.id)
    requirement = make_requirement(
        db,
        project.id,
        "Deliver a responsive landing page with a contact form.",
    )
    freelancer_token = login_token(client, freelancer.email)
    upload = upload_evidence(
        client,
        freelancer_token,
        project.id,
        receipt_pdf_bytes(),
    )
    assert upload.status_code == 201, upload.text

    owner_token = login_token(client, owner.email)
    analysis = run_analysis(client, owner_token, project.id)
    assert analysis.status_code == 201, analysis.text

    return {
        "owner": owner,
        "freelancer": freelancer,
        "project": project,
        "requirement": requirement,
        "owner_token": owner_token,
        "freelancer_token": freelancer_token,
        "analysis": analysis.json(),
        "evidence_id": upload.json()["id"],
    }
