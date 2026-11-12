from app.models import Report
from app.security import ROLE_CLIENT, ROLE_FREELANCER, ROLE_REVIEWER

from tests.helpers import (
    analysed_project,
    auth_headers,
    change_status,
    create_user,
    generate_report,
    login_token,
    make_project,
    run_analysis,
    upload_evidence,
    receipt_pdf_bytes,
)


def test_report_is_built_from_persisted_analysis(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    analysis = data["analysis"]
    token = data["owner_token"]

    response = generate_report(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["kind"] == "project_investigation_report"
    assert body["schema_version"] == "1.0"
    assert body["status"] in {"completed", "completed_with_warnings"}
    assert body["project"]["project_id"] == project.id
    assert body["project"]["title"] == project.title
    assert body["project"]["client_id"] == data["owner"].id
    assert body["project"]["freelancer_id"] == data["freelancer"].id
    assert body["analysis_report_id"] == analysis["report_id"]
    assert body["analysis_generated_at"] == analysis["generated_at"]
    assert body["ai_package_version"] == analysis["ai_package_version"]
    assert body["human_review_required"] is True
    assert body["final_decision_notice"] == analysis["final_decision_notice"]
    assert "advisory" in body["advisory_notice"].lower()
    assert "does not" in body["advisory_notice"].lower()
    assert "human_reviews" not in body

    report_finding = body["requirement_findings"][0]
    analysis_finding = analysis["requirement_findings"][0]
    assert report_finding["requirement_id"] == analysis_finding["requirement_id"]
    assert report_finding["requirement_text"] == analysis_finding["requirement_text"]
    assert report_finding["status"] == analysis_finding["status"]
    assert report_finding["confidence"] == analysis_finding["confidence"]
    assert report_finding["rationale"] == analysis_finding["rationale"]
    assert report_finding["supporting_evidence_ids"] == (
        analysis_finding["supporting_evidence_ids"]
    )
    assert report_finding["contradicting_evidence_ids"] == (
        analysis_finding["contradicting_evidence_ids"]
    )
    assert report_finding["cited_evidence_ids"] == (
        analysis_finding["cited_evidence_ids"]
    )
    assert report_finding["requires_human_review"] is True
    assert report_finding["human_review_reason"]

    assert [entry["evidence_id"] for entry in body["evidence_inventory"]] == [
        data["evidence_id"]
    ]
    assert body["evidence_inventory"][0]["filename"] == "receipt.pdf"
    assert body["evidence_inventory"][0]["status"] == "processed"

    latest = client.get(
        f"/projects/{project.id}/reports/latest",
        headers=auth_headers(token),
    )
    assert latest.status_code == 200, latest.text
    assert latest.json()["report_id"] == body["report_id"]

    listing = client.get(
        f"/projects/{project.id}/reports",
        headers=auth_headers(token),
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["report_id"] == body["report_id"]
    assert listing.json()["items"][0]["analysis_report_id"] == (
        analysis["report_id"]
    )
    assert listing.json()["items"][0]["requirement_count"] == 1

    specific = client.get(
        f"/projects/{project.id}/reports/{body['report_id']}",
        headers=auth_headers(token),
    )
    assert specific.status_code == 200, specific.text
    assert specific.json()["report_id"] == body["report_id"]

    # Both an analysis snapshot and a report are stored, but the report list
    # only exposes report snapshots.
    assert db.query(Report).count() == 2

    reviewer = create_user(db, "p9-report-reviewer", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)
    assert (
        client.get(
            f"/projects/{project.id}/reports/{body['report_id']}",
            headers=auth_headers(reviewer_token),
        ).status_code
        == 200
    )


def test_report_requires_persisted_analysis(client, db):
    owner = create_user(db, "p9-no-analysis-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-no-analysis-fl", ROLE_FREELANCER)
    project = make_project(db, "No analysis project", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    response = generate_report(client, token, project.id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert db.query(Report).count() == 0


def test_report_rejects_stale_requirement_analysis(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    requirement = data["requirement"]
    token = data["owner_token"]

    updated = client.patch(
        f"/projects/{project.id}/requirements/{requirement.id}",
        json={
            "text": "Deliver a responsive landing page with a contact "
            "form and analytics."
        },
        headers=auth_headers(token),
    )
    assert updated.status_code == 200, updated.text

    response = generate_report(client, token, project.id)
    assert response.status_code == 409
    assert "requirements changed" in response.json()["error"]["message"].lower()
    assert db.query(Report).count() == 1

    rerun = run_analysis(client, token, project.id)
    assert rerun.status_code == 201, rerun.text

    regenerated = generate_report(client, token, project.id)
    assert regenerated.status_code == 201, regenerated.text
    assert regenerated.json()["requirement_findings"][0][
        "requirement_text"
    ] == "Deliver a responsive landing page with a contact form and analytics."


def test_report_rejects_analysis_when_evidence_was_added(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    token = data["owner_token"]

    second = upload_evidence(
        client,
        data["freelancer_token"],
        project.id,
        receipt_pdf_bytes(),
        filename="second-receipt.pdf",
    )
    assert second.status_code == 201, second.text

    response = generate_report(client, token, project.id)
    assert response.status_code == 409
    assert "evidence changed" in response.json()["error"]["message"].lower()
    assert db.query(Report).count() == 1

    rerun = run_analysis(client, token, project.id)
    assert rerun.status_code == 201, rerun.text
    regenerated = generate_report(client, token, project.id)
    assert regenerated.status_code == 201, regenerated.text
    assert len(regenerated.json()["evidence_inventory"]) == 2


def test_report_does_not_expose_reviewer_notes(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    owner_token = data["owner_token"]
    reviewer = create_user(db, "p9-report-private-rev", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)

    assert change_status(
        client, owner_token, project.id, "in_progress"
    ).status_code == 200
    assert change_status(
        client, owner_token, project.id, "under_review"
    ).status_code == 200

    private_note = "Confidential reviewer reasoning that must stay private."
    reviewed = client.post(
        f"/projects/{project.id}/reviews",
        json={"decision": "verified", "notes": private_note},
        headers=auth_headers(reviewer_token),
    )
    assert reviewed.status_code == 201, reviewed.text

    report = generate_report(client, owner_token, project.id)
    assert report.status_code == 201, report.text
    assert "human_reviews" not in report.json()
    assert private_note not in report.text


def test_reports_are_project_scoped_and_authorized(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    token = data["owner_token"]
    report = generate_report(client, token, project.id)
    report_id = report.json()["report_id"]

    other_owner = create_user(db, "p9-report-other-owner", ROLE_CLIENT)
    other_freelancer = create_user(
        db, "p9-report-other-fl", ROLE_FREELANCER
    )
    other_project = make_project(
        db, "Other report project", other_owner.id, other_freelancer.id
    )
    other_token = login_token(client, other_owner.email)

    assert (
        generate_report(client, other_token, project.id).status_code
        == 403
    )
    assert (
        client.get(
            f"/projects/{project.id}/reports/{report_id}",
            headers=auth_headers(other_token),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/projects/{other_project.id}/reports/{report_id}",
            headers=auth_headers(other_token),
        ).status_code
        == 404
    )
    assert (
        generate_report(
            client,
            other_token,
            other_project.id,
            analysis_report_id=data["analysis"]["report_id"],
        ).status_code
        == 404
    )

    # A report id is not a valid analysis snapshot id.
    wrong_kind = generate_report(
        client,
        token,
        project.id,
        analysis_report_id=report_id,
    )
    assert wrong_kind.status_code == 404
