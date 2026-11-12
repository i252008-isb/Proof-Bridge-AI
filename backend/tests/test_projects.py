import pytest

from app.models import CaseStatusLog, Project, User
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    hash_password
)


PASSWORD = "correct-password-123"


def register(client, email, role, name="Project User"):
    response = client.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": PASSWORD,
            "role": role
        }
    )

    assert response.status_code == 201, response.text

    return response.json()


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


def create_user(db, email, role):
    user = User(
        name="Direct User",
        email=email,
        password_hash=hash_password(PASSWORD),
        role=role
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def make_project(
    db,
    title,
    client_id,
    freelancer_id,
    status="created"
):
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


def create_project_via_api(
    client,
    token,
    freelancer_id,
    title="Build a website"
):
    response = client.post(
        "/projects",
        json={
            "title": title,
            "description": "Initial scope",
            "freelancer_id": freelancer_id
        },
        headers=auth_headers(token)
    )

    assert response.status_code == 201, response.text

    return response.json()


# ----------------------------------------------------------------- create

def test_client_can_create_project_with_existing_freelancer(client, db):
    client_user = register(client, "creator@example.com", "client")
    freelancer = register(
        client,
        "assigned-freelancer@example.com",
        "freelancer"
    )
    token = login_token(client, client_user["email"])

    body = create_project_via_api(
        client,
        token,
        freelancer["id"],
        title="  Website redesign  "
    )

    assert body["title"] == "Website redesign"
    assert body["status"] == "created"
    assert body["client_id"] == client_user["id"]
    assert body["freelancer_id"] == freelancer["id"]

    logs = db.query(CaseStatusLog).filter(
        CaseStatusLog.project_id == body["id"]
    ).all()

    assert len(logs) == 1
    assert logs[0].status == "created"
    assert logs[0].changed_by == client_user["id"]
    assert logs[0].note == "Project created."


def test_project_creation_requires_client_role(client, db):
    freelancer = register(
        client,
        "creating-freelancer@example.com",
        "freelancer"
    )
    reviewer = create_user(db, "creating-reviewer@example.com", ROLE_REVIEWER)
    another_client = register(
        client,
        "assignable-client@example.com",
        "client"
    )

    freelancer_token = login_token(client, freelancer["email"])
    reviewer_token = login_token(client, reviewer.email)

    for token in (freelancer_token, reviewer_token):
        response = client.post(
            "/projects",
            json={
                "title": "Not allowed",
                "freelancer_id": another_client["id"]
            },
            headers=auth_headers(token)
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


def test_project_creation_requires_existing_freelancer(client, db):
    client_user = register(client, "invalid-freelancer@example.com", "client")
    other_client = register(
        client,
        "wrong-role-user@example.com",
        "client"
    )
    token = login_token(client, client_user["email"])

    missing = client.post(
        "/projects",
        json={"title": "Missing person", "freelancer_id": 999999},
        headers=auth_headers(token)
    )

    wrong_role = client.post(
        "/projects",
        json={
            "title": "Wrong role",
            "freelancer_id": other_client["id"]
        },
        headers=auth_headers(token)
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert wrong_role.status_code == 400
    assert wrong_role.json()["error"]["code"] == "bad_request"


# ------------------------------------------------------------------ lists

def test_project_listing_is_scoped_for_each_role(client, db):
    client_a = create_user(db, "list-client-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "list-client-b@example.com", ROLE_CLIENT)
    freelancer_a = create_user(
        db,
        "list-freelancer-a@example.com",
        ROLE_FREELANCER
    )
    freelancer_b = create_user(
        db,
        "list-freelancer-b@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(db, "list-reviewer@example.com", ROLE_REVIEWER)

    project_1 = make_project(db, "A project one", client_a.id, freelancer_a.id)
    project_2 = make_project(db, "B project two", client_b.id, freelancer_b.id)
    project_3 = make_project(db, "A project three", client_a.id, freelancer_b.id)

    def listed_ids(user):
        token = login_token(client, user.email)
        response = client.get(
            "/projects",
            headers=auth_headers(token)
        )

        assert response.status_code == 200

        return {project["id"] for project in response.json()}

    assert listed_ids(client_a) == {project_1.id, project_3.id}
    assert listed_ids(client_b) == {project_2.id}
    assert listed_ids(freelancer_a) == {project_1.id}
    assert listed_ids(freelancer_b) == {project_2.id, project_3.id}
    assert listed_ids(reviewer) == {
        project_1.id,
        project_2.id,
        project_3.id
    }


# ----------------------------------------------------------------- detail

def test_project_detail_access_rules(client, db):
    client_a = create_user(db, "detail-client-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "detail-client-b@example.com", ROLE_CLIENT)
    freelancer_a = create_user(
        db,
        "detail-freelancer-a@example.com",
        ROLE_FREELANCER
    )
    freelancer_b = create_user(
        db,
        "detail-freelancer-b@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(db, "detail-reviewer@example.com", ROLE_REVIEWER)

    project = make_project(
        db,
        "Private project",
        client_a.id,
        freelancer_a.id
    )

    def status_for(user):
        token = login_token(client, user.email)

        return client.get(
            f"/projects/{project.id}",
            headers=auth_headers(token)
        )

    assert status_for(client_a).status_code == 200
    assert status_for(freelancer_a).status_code == 200
    assert status_for(reviewer).status_code == 200

    assert status_for(client_b).status_code == 403
    assert status_for(freelancer_b).status_code == 403


# ----------------------------------------------------------------- update

def test_client_can_update_permitted_project_fields(client, db):
    client_user = register(client, "update-client@example.com", "client")
    freelancer = register(
        client,
        "update-freelancer@example.com",
        "freelancer"
    )
    token = login_token(client, client_user["email"])
    project = create_project_via_api(client, token, freelancer["id"])

    response = client.patch(
        f"/projects/{project['id']}",
        json={
            "title": "Updated title",
            "description": "Updated scope"
        },
        headers=auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated title"
    assert body["description"] == "Updated scope"
    assert body["status"] == "created"

    db.expire_all()
    stored = db.get(Project, project["id"])
    assert stored.title == "Updated title"

    logs = db.query(CaseStatusLog).filter(
        CaseStatusLog.project_id == project["id"]
    ).order_by(CaseStatusLog.id).all()

    assert logs[-1].note == "Project details updated."
    assert logs[-1].status == "created"
    assert logs[-1].changed_by == client_user["id"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": None},
        {"freelancer_id": 2},
        {"client_id": 2},
        {"status": "in_progress"},
    ]
)
def test_update_rejects_unsupported_or_ownership_changes(
    client,
    db,
    payload
):
    client_user = register(
        client,
        f"bad-update-{abs(hash(str(payload))) % 100000}@example.com",
        "client"
    )
    freelancer = register(
        client,
        f"bad-update-free-{abs(hash(str(payload))) % 100000}@example.com",
        "freelancer"
    )
    token = login_token(client, client_user["email"])
    project = create_project_via_api(client, token, freelancer["id"])

    response = client.patch(
        f"/projects/{project['id']}",
        json=payload,
        headers=auth_headers(token)
    )

    assert response.status_code == 422


def test_only_project_owner_can_update_project(client, db):
    client_a = create_user(db, "owner-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "owner-b@example.com", ROLE_CLIENT)
    freelancer = create_user(
        db,
        "owner-freelancer@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(db, "owner-reviewer@example.com", ROLE_REVIEWER)
    project = make_project(db, "Owner project", client_a.id, freelancer.id)

    for user in (freelancer, client_b, reviewer):
        token = login_token(client, user.email)
        response = client.patch(
            f"/projects/{project.id}",
            json={"title": "Unauthorized edit"},
            headers=auth_headers(token)
        )

        assert response.status_code == 403

    owner_token = login_token(client, client_a.email)
    missing = client.patch(
        "/projects/999999",
        json={"title": "Missing project"},
        headers=auth_headers(owner_token)
    )

    assert missing.status_code == 404


def test_terminal_project_cannot_be_updated(client, db):
    client_user = create_user(db, "terminal-client@example.com", ROLE_CLIENT)
    freelancer = create_user(
        db,
        "terminal-freelancer@example.com",
        ROLE_FREELANCER
    )
    project = make_project(
        db,
        "Completed project",
        client_user.id,
        freelancer.id,
        status="completed"
    )
    token = login_token(client, client_user.email)

    response = client.patch(
        f"/projects/{project.id}",
        json={"title": "Should not change"},
        headers=auth_headers(token)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


# ----------------------------------------------------------------- status

def test_project_status_is_visible_to_participants_and_reviewer(client, db):
    client_user = register(client, "status-client@example.com", "client")
    freelancer = register(
        client,
        "status-freelancer@example.com",
        "freelancer"
    )
    outsider = register(
        client,
        "status-outsider@example.com",
        "client"
    )
    reviewer = create_user(db, "status-reviewer@example.com", ROLE_REVIEWER)
    token = login_token(client, client_user["email"])
    project = create_project_via_api(client, token, freelancer["id"])

    def status_for(user):
        return client.get(
            f"/projects/{project['id']}/status",
            headers=auth_headers(login_token(client, user))
        )

    owner_response = status_for(client_user["email"])
    assert owner_response.status_code == 200
    assert owner_response.json()["status"] == "created"
    assert [entry["status"] for entry in owner_response.json()["history"]] == [
        "created"
    ]

    assert status_for(freelancer["email"]).status_code == 200
    assert status_for(outsider["email"]).status_code == 403
    assert status_for(reviewer.email).status_code == 200


def test_valid_status_transitions_are_applied_and_recorded(client, db):
    client_user = register(client, "chain-client@example.com", "client")
    freelancer = register(
        client,
        "chain-freelancer@example.com",
        "freelancer"
    )
    token = login_token(client, client_user["email"])
    project = create_project_via_api(client, token, freelancer["id"])

    first = client.patch(
        f"/projects/{project['id']}/status",
        json={"status": "in_progress", "note": "Work started"},
        headers=auth_headers(token)
    )
    second = client.patch(
        f"/projects/{project['id']}/status",
        json={"status": "under_review"},
        headers=auth_headers(token)
    )
    third = client.patch(
        f"/projects/{project['id']}/status",
        json={"status": "completed"},
        headers=auth_headers(token)
    )

    assert first.status_code == 200
    assert first.json()["status"] == "in_progress"
    assert second.status_code == 200
    assert third.status_code == 200
    assert third.json()["status"] == "completed"
    assert [entry["status"] for entry in third.json()["history"]] == [
        "created",
        "in_progress",
        "under_review",
        "completed"
    ]

    db.expire_all()
    assert db.get(Project, project["id"]).status == "completed"

    logs = db.query(CaseStatusLog).filter(
        CaseStatusLog.project_id == project["id"]
    ).order_by(CaseStatusLog.id).all()

    assert [log.status for log in logs] == [
        "created",
        "in_progress",
        "under_review",
        "completed"
    ]
    assert logs[1].note == "Work started"
    assert all(log.changed_by == client_user["id"] for log in logs)


def test_invalid_status_transitions_are_rejected(client, db):
    client_user = register(client, "invalid-status@example.com", "client")
    freelancer = register(
        client,
        "invalid-status-free@example.com",
        "freelancer"
    )
    token = login_token(client, client_user["email"])
    project = create_project_via_api(client, token, freelancer["id"])

    skipped = client.patch(
        f"/projects/{project['id']}/status",
        json={"status": "completed"},
        headers=auth_headers(token)
    )
    repeated = client.patch(
        f"/projects/{project['id']}/status",
        json={"status": "created"},
        headers=auth_headers(token)
    )
    unknown = client.patch(
        f"/projects/{project['id']}/status",
        json={"status": "shipped"},
        headers=auth_headers(token)
    )

    assert skipped.status_code == 409
    assert "Allowed next statuses" in skipped.json()["error"]["message"]
    assert repeated.status_code == 409
    assert unknown.status_code == 422


def test_terminal_status_cannot_change(client, db):
    client_user = create_user(db, "done-client@example.com", ROLE_CLIENT)
    freelancer = create_user(
        db,
        "done-freelancer@example.com",
        ROLE_FREELANCER
    )
    project = make_project(
        db,
        "Finished project",
        client_user.id,
        freelancer.id,
        status="completed"
    )
    token = login_token(client, client_user.email)

    response = client.patch(
        f"/projects/{project.id}/status",
        json={"status": "in_progress"},
        headers=auth_headers(token)
    )

    assert response.status_code == 409


def test_only_project_owner_can_change_status(client, db):
    client_a = create_user(db, "status-owner-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "status-owner-b@example.com", ROLE_CLIENT)
    freelancer = create_user(
        db,
        "status-owner-freelancer@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(
        db,
        "status-owner-reviewer@example.com",
        ROLE_REVIEWER
    )
    project = make_project(
        db,
        "Status ownership project",
        client_a.id,
        freelancer.id
    )

    for user in (freelancer, client_b, reviewer):
        token = login_token(client, user.email)
        response = client.patch(
            f"/projects/{project.id}/status",
            json={"status": "in_progress"},
            headers=auth_headers(token)
        )

        assert response.status_code == 403

    owner_token = login_token(client, client_a.email)
    missing = client.patch(
        "/projects/999999/status",
        json={"status": "in_progress"},
        headers=auth_headers(owner_token)
    )

    assert missing.status_code == 404
