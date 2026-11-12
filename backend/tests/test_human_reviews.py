from app.main import app
from app.models import CaseStatusLog, HumanReview, Project, Report
from app.security import ROLE_CLIENT, ROLE_FREELANCER, ROLE_REVIEWER

from tests.helpers import (
    analysed_project,
    auth_headers,
    change_status,
    create_user,
    login_token,
    make_project,
    receipt_pdf_bytes,
    run_analysis,
    upload_evidence,
)


REVIEW_NOTES = "The cited evidence matches the agreed deliverable."


def _to_under_review(client, token, project_id):
    first = change_status(client, token, project_id, "in_progress")
    assert first.status_code == 200, first.text

    second = change_status(
        client,
        token,
        project_id,
        "under_review",
        "Evidence is ready for human review.",
    )
    assert second.status_code == 200, second.text


def test_reviewer_can_review_and_decision_is_audited(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    owner_token = data["owner_token"]
    reviewer = create_user(db, "p9-reviewer", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)
    _to_under_review(client, owner_token, project.id)

    pending = client.get(
        "/reviews/pending", headers=auth_headers(reviewer_token)
    )
    assert pending.status_code == 200, pending.text
    pending_item = next(
        item
        for item in pending.json()["items"]
        if item["project_id"] == project.id
    )
    assert pending_item["latest_analysis_report_id"] == (
        data["analysis"]["report_id"]
    )
    assert pending_item["requirement_count"] == 1
    assert pending_item["evidence_count"] == 1

    assert (
        client.get(
            "/reviews/pending", headers=auth_headers(owner_token)
        ).status_code
        == 403
    )

    context = client.get(
        f"/projects/{project.id}/reviews/context",
        headers=auth_headers(reviewer_token),
    )
    assert context.status_code == 200, context.text
    context_body = context.json()
    assert context_body["project"]["id"] == project.id
    assert context_body["latest_analysis"]["report_id"] == (
        data["analysis"]["report_id"]
    )
    assert [entry["id"] for entry in context_body["evidence"]] == [
        data["evidence_id"]
    ]
    assert context_body["status_history"][-1]["status"] == "under_review"
    assert context_body["reviews"] == []

    analysis_content_before = dict(
        db.query(Report)
        .filter_by(id=data["analysis"]["report_id"])
        .one()
        .content
    )

    submitted = client.post(
        f"/projects/{project.id}/reviews",
        json={"decision": "verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    assert body["project_status"] == "completed"
    assert body["review"]["project_id"] == project.id
    assert body["review"]["reviewer_id"] == reviewer.id
    assert body["review"]["decision"] == "verified"
    assert body["review"]["notes"] == REVIEW_NOTES
    assert body["review"]["created_at"]

    db.expire_all()
    assert db.query(HumanReview).count() == 1
    review_row = db.query(HumanReview).one()
    assert review_row.reviewer_id == reviewer.id

    refreshed_project = db.get(Project, project.id)
    assert refreshed_project.status == "completed"

    last_log = (
        db.query(CaseStatusLog)
        .filter(CaseStatusLog.project_id == project.id)
        .order_by(CaseStatusLog.id.desc())
        .first()
    )
    assert last_log.status == "completed"
    assert last_log.changed_by == reviewer.id
    assert last_log.created_at is not None
    assert "verified" in last_log.note
    # Reviewer notes stay in reviewer-only endpoints and never appear in
    # the case status audit trail visible to project participants.
    assert REVIEW_NOTES not in last_log.note

    for participant_token in (owner_token, data["freelancer_token"]):
        status_view = client.get(
            f"/projects/{project.id}/status",
            headers=auth_headers(participant_token),
        )
        assert status_view.status_code == 200
        assert REVIEW_NOTES not in status_view.text

        history_view = client.get(
            f"/projects/{project.id}/history",
            headers=auth_headers(participant_token),
        )
        assert history_view.status_code == 200
        assert REVIEW_NOTES not in history_view.text

    # Human decisions never rewrite the stored AI findings.
    analysis_row = (
        db.query(Report)
        .filter_by(id=data["analysis"]["report_id"])
        .one()
    )
    assert analysis_row.content == analysis_content_before

    history = client.get(
        f"/projects/{project.id}/reviews",
        headers=auth_headers(reviewer_token),
    )
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == body["review"]["id"]

    single = client.get(
        f"/projects/{project.id}/reviews/{body['review']['id']}",
        headers=auth_headers(reviewer_token),
    )
    assert single.status_code == 200, single.text
    assert single.json()["decision"] == "verified"

    pending_after = client.get(
        "/reviews/pending", headers=auth_headers(reviewer_token)
    )
    assert pending_after.status_code == 200
    assert all(
        item["project_id"] != project.id
        for item in pending_after.json()["items"]
    )


def test_review_requires_analysis_and_reviewable_status(client, db):
    owner = create_user(db, "p9-review-no-analysis-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-review-no-analysis-fl", ROLE_FREELANCER)
    reviewer = create_user(db, "p9-review-no-analysis-rev", ROLE_REVIEWER)
    project = make_project(
        db, "Review without analysis", owner.id, freelancer.id
    )
    owner_token = login_token(client, owner.email)
    reviewer_token = login_token(client, reviewer.email)
    _to_under_review(client, owner_token, project.id)

    missing_analysis = client.post(
        f"/projects/{project.id}/reviews",
        json={"decision": "verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert missing_analysis.status_code == 404
    assert db.query(HumanReview).count() == 0

    data = analysed_project(client, db)
    wrong_status = client.post(
        f"/projects/{data['project'].id}/reviews",
        json={"decision": "verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert wrong_status.status_code == 409
    assert "under_review" in wrong_status.json()["error"]["message"]
    assert db.query(HumanReview).count() == 0


def test_needs_more_evidence_returns_case_to_progress(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    owner_token = data["owner_token"]
    reviewer = create_user(db, "p9-review-more-evidence", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)
    _to_under_review(client, owner_token, project.id)

    first = client.post(
        f"/projects/{project.id}/reviews",
        json={
            "decision": "needs_more_evidence",
            "notes": "The delivery invoice and final export are missing.",
        },
        headers=auth_headers(reviewer_token),
    )
    assert first.status_code == 201, first.text
    assert first.json()["project_status"] == "in_progress"

    second = change_status(
        client,
        owner_token,
        project.id,
        "under_review",
        "Additional evidence supplied.",
    )
    assert second.status_code == 200, second.text

    final = client.post(
        f"/projects/{project.id}/reviews",
        json={"decision": "partially_verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert final.status_code == 201, final.text
    assert final.json()["project_status"] == "completed"

    db.expire_all()
    assert db.query(HumanReview).count() == 2
    history = client.get(
        f"/projects/{project.id}/reviews",
        headers=auth_headers(reviewer_token),
    )
    assert history.status_code == 200
    assert [item["decision"] for item in history.json()["items"]] == [
        "needs_more_evidence",
        "partially_verified",
    ]


def test_review_endpoints_are_reviewer_only_and_immutable(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    reviewer = create_user(db, "p9-review-immutable", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)
    owner_token = data["owner_token"]
    _to_under_review(client, owner_token, project.id)

    for token in (owner_token, data["freelancer_token"]):
        headers = auth_headers(token)
        assert (
            client.get("/reviews/pending", headers=headers).status_code
            == 403
        )
        assert (
            client.get(
                f"/projects/{project.id}/reviews/context", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/projects/{project.id}/reviews", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/projects/{project.id}/reviews",
                json={"decision": "verified", "notes": REVIEW_NOTES},
                headers=headers,
            ).status_code
            == 403
        )

    assert client.get("/reviews/pending").status_code == 401

    submitted = client.post(
        f"/projects/{project.id}/reviews",
        json={"decision": "verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert submitted.status_code == 201, submitted.text
    review_id = submitted.json()["review"]["id"]

    methods = set(
        app.openapi()["paths"][
            "/projects/{project_id}/reviews/{review_id}"
        ]
    )
    assert methods == {"get"}

    patch = client.patch(
        f"/projects/{project.id}/reviews/{review_id}",
        json={"decision": "rejected", "notes": "Changed my mind entirely."},
        headers=auth_headers(reviewer_token),
    )
    assert patch.status_code == 405
    assert patch.json()["error"]["code"] == "method_not_allowed"

    delete = client.delete(
        f"/projects/{project.id}/reviews/{review_id}",
        headers=auth_headers(reviewer_token),
    )
    assert delete.status_code == 405


def test_review_rejects_stale_analysis_after_evidence_changes(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    owner_token = data["owner_token"]
    reviewer = create_user(db, "p9-review-stale", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)
    _to_under_review(client, owner_token, project.id)

    added = upload_evidence(
        client,
        data["freelancer_token"],
        project.id,
        receipt_pdf_bytes(),
        filename="additional-receipt.pdf",
    )
    assert added.status_code == 201, added.text

    stale = client.post(
        f"/projects/{project.id}/reviews",
        json={"decision": "verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert stale.status_code == 409, stale.text
    assert "evidence changed" in stale.json()["error"]["message"].lower()
    assert db.query(HumanReview).count() == 0

    db.expire_all()
    assert db.get(Project, project.id).status == "under_review"

    rerun = run_analysis(client, owner_token, project.id)
    assert rerun.status_code == 201, rerun.text

    reviewed = client.post(
        f"/projects/{project.id}/reviews",
        json={"decision": "verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["project_status"] == "completed"


def test_review_is_scoped_to_its_project(client, db):
    first = analysed_project(client, db, title="First review case")
    second = analysed_project(client, db, title="Second review case")
    reviewer = create_user(db, "p9-review-scope", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)
    _to_under_review(client, first["owner_token"], first["project"].id)

    submitted = client.post(
        f"/projects/{first['project'].id}/reviews",
        json={"decision": "verified", "notes": REVIEW_NOTES},
        headers=auth_headers(reviewer_token),
    )
    assert submitted.status_code == 201, submitted.text
    review_id = submitted.json()["review"]["id"]

    wrong_project = client.get(
        f"/projects/{second['project'].id}/reviews/{review_id}",
        headers=auth_headers(reviewer_token),
    )
    assert wrong_project.status_code == 404
    assert wrong_project.json()["error"]["code"] == "not_found"
