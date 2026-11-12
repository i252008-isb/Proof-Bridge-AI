"""End-to-end workflow through the real HTTP API.

Registration -> project -> requirement -> agreement -> evidence -> AI
analysis -> report -> status workflow -> human review -> audit history.
All external AI providers are deterministic mocks configured by conftest.
"""

from uuid import uuid4

from app.models import Project
from app.security import ROLE_REVIEWER

from tests.helpers import (
    auth_headers,
    create_user,
    login_token,
    receipt_pdf_bytes,
    upload_evidence,
)


PASSWORD = "correct-password-123"


def register(client, prefix, role, name):
    email = f"{prefix}-{uuid4().hex}@example.com"
    response = client.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": PASSWORD,
            "role": role,
        },
    )

    assert response.status_code == 201, response.text

    return response.json(), email


def test_full_workflow_from_registration_to_human_review(client, db):
    client_user, client_email = register(
        client, "e2e-client", "client", "E2E Client"
    )
    freelancer, freelancer_email = register(
        client, "e2e-freelancer", "freelancer", "E2E Freelancer"
    )
    reviewer = create_user(db, "e2e-reviewer", ROLE_REVIEWER)

    client_token = login_token(client, client_email)
    freelancer_token = login_token(client, freelancer_email)
    reviewer_token = login_token(client, reviewer.email)

    client_headers = auth_headers(client_token)
    freelancer_headers = auth_headers(freelancer_token)
    reviewer_headers = auth_headers(reviewer_token)

    project_payload = {
        "title": "E2E landing page delivery",
        "description": (
            "The freelancer delivered a landing page, but the client says "
            "the contact form and confirmation email are missing."
        ),
        "freelancer_id": freelancer["id"],
    }

    assert client.post(
        "/projects", json=project_payload, headers=freelancer_headers
    ).status_code == 403
    assert client.post(
        "/projects", json=project_payload, headers=reviewer_headers
    ).status_code == 403

    project_response = client.post(
        "/projects", json=project_payload, headers=client_headers
    )
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()
    project_id = project["id"]
    assert project["client_id"] == client_user["id"]
    assert project["freelancer_id"] == freelancer["id"]

    requirement_response = client.post(
        f"/projects/{project_id}/requirements",
        json={
            "text": (
                "Deliver a responsive landing page with a working contact "
                "form and email confirmation."
            ),
            "category": "deliverable",
            "source_quote": "Agreement section 2: contact form required.",
        },
        headers=client_headers,
    )
    assert requirement_response.status_code == 201, requirement_response.text
    requirement_id = requirement_response.json()["id"]

    agreement_response = client.post(
        f"/projects/{project_id}/agreement",
        files={
            "file": (
                "agreement.pdf",
                receipt_pdf_bytes(),
                "application/pdf",
            )
        },
        headers=client_headers,
    )
    assert agreement_response.status_code == 201, agreement_response.text
    assert agreement_response.json()["agreement_name"] == "agreement.pdf"

    assert client.post(
        f"/projects/{project_id}/agreement",
        files={"file": ("agreement.pdf", receipt_pdf_bytes(), "application/pdf")},
        headers=freelancer_headers,
    ).status_code == 403

    assert client.post(
        f"/projects/{project_id}/evidence",
        files={"file": ("evidence.pdf", receipt_pdf_bytes(), "application/pdf")},
        headers=client_headers,
    ).status_code == 403

    evidence_response = upload_evidence(
        client,
        freelancer_token,
        project_id,
        receipt_pdf_bytes(),
        filename="delivery-receipt.pdf",
    )
    assert evidence_response.status_code == 201, evidence_response.text
    evidence_id = evidence_response.json()["id"]

    analysis_response = client.post(
        f"/projects/{project_id}/analysis",
        headers=client_headers,
    )
    assert analysis_response.status_code == 201, analysis_response.text
    analysis = analysis_response.json()
    assert analysis["human_review_required"] is True
    assert analysis["project_id"] == project_id
    assert analysis["input_summary"]["requirement_ids"] == [requirement_id]
    assert analysis["input_summary"]["evidence_ids"] == [evidence_id]
    assert analysis["requirement_findings"][0]["requirement_id"] == requirement_id
    assert analysis["requirement_findings"][0]["requires_human_review"] is True

    report_response = client.post(
        f"/projects/{project_id}/reports",
        headers=client_headers,
    )
    assert report_response.status_code == 201, report_response.text
    report = report_response.json()
    assert report["analysis_report_id"] == analysis["report_id"]
    assert report["human_review_required"] is True
    assert "advisory" in report["advisory_notice"].lower()
    assert "human_reviews" not in report
    assert [entry["evidence_id"] for entry in report["evidence_inventory"]] == [
        evidence_id
    ]

    assert client.get(
        f"/projects/{project_id}/analysis", headers=freelancer_headers
    ).status_code == 200
    assert client.get(
        f"/projects/{project_id}/reports/latest", headers=freelancer_headers
    ).status_code == 200
    assert client.get(
        f"/projects/{project_id}/agreement/download",
        headers=freelancer_headers,
    ).status_code == 200
    assert client.get(
        f"/projects/{project_id}/evidence/{evidence_id}/download",
        headers=client_headers,
    ).status_code == 200

    started = client.patch(
        f"/projects/{project_id}/status",
        json={"status": "in_progress", "note": "Work started."},
        headers=client_headers,
    )
    assert started.status_code == 200, started.text
    submitted = client.patch(
        f"/projects/{project_id}/status",
        json={"status": "under_review", "note": "Evidence submitted."},
        headers=client_headers,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "under_review"

    pending = client.get("/reviews/pending", headers=reviewer_headers)
    assert pending.status_code == 200, pending.text
    assert any(
        item["project_id"] == project_id
        for item in pending.json()["items"]
    )

    context = client.get(
        f"/projects/{project_id}/reviews/context",
        headers=reviewer_headers,
    )
    assert context.status_code == 200, context.text
    context_body = context.json()
    assert context_body["project"]["id"] == project_id
    assert context_body["latest_analysis"]["report_id"] == analysis["report_id"]
    assert context_body["reviews"] == []

    private_note = (
        "E2E confidential reviewer note: the cited evidence matches the "
        "agreed deliverable."
    )
    review_response = client.post(
        f"/projects/{project_id}/reviews",
        json={"decision": "verified", "notes": private_note},
        headers=reviewer_headers,
    )
    assert review_response.status_code == 201, review_response.text
    assert review_response.json()["project_status"] == "completed"

    status_response = client.get(
        f"/projects/{project_id}/status", headers=client_headers
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert private_note not in status_response.text

    history_response = client.get(
        f"/projects/{project_id}/history", headers=client_headers
    )
    assert history_response.status_code == 200, history_response.text
    history = history_response.json()
    assert history["current_status"] == "completed"
    event_types = {event["event_type"] for event in history["events"]}
    assert {"status", "analysis", "report", "human_review"} <= event_types
    assert private_note not in history_response.text

    latest_report = client.get(
        f"/projects/{project_id}/reports/latest", headers=client_headers
    )
    assert latest_report.status_code == 200
    assert private_note not in latest_report.text

    late_change = client.patch(
        f"/projects/{project_id}",
        json={"title": "Late change after completion"},
        headers=client_headers,
    )
    assert late_change.status_code == 409

    assert client.get(
        f"/projects/{project_id}/reviews", headers=freelancer_headers
    ).status_code == 403

    db.expire_all()
    stored = db.get(Project, project_id)
    assert stored.status == "completed"
    assert stored.agreement_path
    assert stored.agreement_path not in history_response.text
