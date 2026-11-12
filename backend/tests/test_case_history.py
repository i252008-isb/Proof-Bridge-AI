from app.models import CaseStatusLog, Project
from app.security import ROLE_CLIENT, ROLE_FREELANCER, ROLE_REVIEWER

from tests.helpers import (
    analysed_project,
    auth_headers,
    change_status,
    create_user,
    generate_report,
    login_token,
    make_project,
)


def test_case_history_combines_audit_sources(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    owner_token = data["owner_token"]

    report = generate_report(client, owner_token, project.id)
    assert report.status_code == 201, report.text

    assert change_status(
        client, owner_token, project.id, "in_progress"
    ).status_code == 200
    assert change_status(
        client,
        owner_token,
        project.id,
        "under_review",
        "Submitted for human review.",
    ).status_code == 200

    reviewer = create_user(db, "p9-history-reviewer", ROLE_REVIEWER)
    reviewer_token = login_token(client, reviewer.email)
    review = client.post(
        f"/projects/{project.id}/reviews",
        json={
            "decision": "verified",
            "notes": "Evidence matches the agreed deliverable.",
        },
        headers=auth_headers(reviewer_token),
    )
    assert review.status_code == 201, review.text

    response = client.get(
        f"/projects/{project.id}/history",
        headers=auth_headers(data["freelancer_token"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["project_id"] == project.id
    assert body["current_status"] == "completed"

    event_types = [event["event_type"] for event in body["events"]]
    assert "status" in event_types
    assert "analysis" in event_types
    assert "report" in event_types
    assert "human_review" in event_types

    timestamps = [event["occurred_at"] for event in body["events"]]
    assert timestamps == sorted(timestamps)

    status_events = [
        event for event in body["events"] if event["event_type"] == "status"
    ]
    assert status_events[0]["status"] == "in_progress"
    assert status_events[-1]["status"] == "completed"
    assert all(event["actor_id"] is not None for event in status_events)
    assert status_events[-1]["actor_id"] == reviewer.id

    human_event = next(
        event
        for event in body["events"]
        if event["event_type"] == "human_review"
    )
    assert human_event["actor_id"] == reviewer.id
    assert human_event["reference_id"] == review.json()["review"]["id"]

    analysis_event = next(
        event
        for event in body["events"]
        if event["event_type"] == "analysis"
    )
    assert analysis_event["reference_id"] == data["analysis"]["report_id"]

    report_event = next(
        event
        for event in body["events"]
        if event["event_type"] == "report"
    )
    assert report_event["reference_id"] == report.json()["report_id"]

    reviewer_view = client.get(
        f"/projects/{project.id}/history",
        headers=auth_headers(reviewer_token),
    )
    assert reviewer_view.status_code == 200
    assert reviewer_view.json()["current_status"] == "completed"


def test_invalid_status_transition_is_rejected_without_a_log(client, db):
    owner = create_user(db, "p9-history-owner", ROLE_CLIENT)
    freelancer = create_user(db, "p9-history-fl", ROLE_FREELANCER)
    project = make_project(db, "Transition case", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    initial_logs = (
        db.query(CaseStatusLog)
        .filter(CaseStatusLog.project_id == project.id)
        .count()
    )
    assert initial_logs == 0

    invalid = change_status(client, token, project.id, "completed")
    assert invalid.status_code == 409
    assert "Allowed next statuses" in invalid.json()["error"]["message"]

    same = change_status(client, token, project.id, "created")
    assert same.status_code == 409

    db.expire_all()
    assert (
        db.query(CaseStatusLog)
        .filter(CaseStatusLog.project_id == project.id)
        .count()
    ) == initial_logs
    assert db.get(Project, project.id).status == "created"

    valid = change_status(
        client,
        token,
        project.id,
        "in_progress",
        "Work started.",
    )
    assert valid.status_code == 200, valid.text

    logs = (
        db.query(CaseStatusLog)
        .filter(CaseStatusLog.project_id == project.id)
        .order_by(CaseStatusLog.id)
        .all()
    )
    assert [log.status for log in logs] == ["in_progress"]
    assert logs[-1].changed_by == owner.id
    assert logs[-1].note == "Work started."
    assert logs[-1].created_at is not None


def test_case_history_is_authorized_and_project_scoped(client, db):
    data = analysed_project(client, db)
    project = data["project"]
    outsider = create_user(db, "p9-history-outsider", ROLE_CLIENT)
    outsider_token = login_token(client, outsider.email)

    assert (
        client.get(
            f"/projects/{project.id}/history",
            headers=auth_headers(outsider_token),
        ).status_code
        == 403
    )
    assert client.get(f"/projects/{project.id}/history").status_code == 401

    missing = client.get(
        "/projects/999999/history",
        headers=auth_headers(data["owner_token"]),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
