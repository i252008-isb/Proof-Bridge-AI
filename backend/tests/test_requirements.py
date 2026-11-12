from uuid import uuid4

import pytest

from app.models import Project, Requirement, User
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    hash_password
)


PASSWORD = "correct-password-123"

REQUIREMENT_TEXT = (
    "The checkout page must accept credit card payments "
    "and show a confirmation number."
)

SOURCE_QUOTE = "Section 3.2: checkout must accept credit card payments."


def register(client, email, role):
    response = client.post(
        "/auth/register",
        json={
            "name": "Requirement User",
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


def make_requirement(
    db,
    project_id,
    text=REQUIREMENT_TEXT,
    category="checkout",
    source_quote=SOURCE_QUOTE
):
    requirement = Requirement(
        project_id=project_id,
        text=text,
        category=category,
        source_quote=source_quote
    )

    db.add(requirement)
    db.commit()
    db.refresh(requirement)

    return requirement


def create_requirement(
    client,
    token,
    project_id,
    text=REQUIREMENT_TEXT,
    category="checkout",
    source_quote=SOURCE_QUOTE
):
    return client.post(
        f"/projects/{project_id}/requirements",
        json={
            "text": text,
            "category": category,
            "source_quote": source_quote
        },
        headers=auth_headers(token)
    )


# ----------------------------------------------------------------- create

def test_client_can_create_requirement(client, db):
    client_user = register(client, "req-creator@example.com", "client")
    freelancer = register(
        client,
        "req-freelancer@example.com",
        "freelancer"
    )
    project = make_project(
        db,
        "Requirement project",
        client_user["id"],
        freelancer["id"]
    )
    token = login_token(client, client_user["email"])

    response = create_requirement(
        client,
        token,
        project.id,
        text=f"  {REQUIREMENT_TEXT}  ",
        category="  checkout  ",
        source_quote=f"  {SOURCE_QUOTE}  "
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == project.id
    assert body["text"] == REQUIREMENT_TEXT
    assert body["category"] == "checkout"
    assert body["source_quote"] == SOURCE_QUOTE
    assert set(body) == {
        "id",
        "project_id",
        "text",
        "category",
        "source_quote"
    }

    stored = db.get(Requirement, body["id"])
    assert stored.text == REQUIREMENT_TEXT


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": "too short"},
        {"text": "          "},
        {"text": REQUIREMENT_TEXT, "project_id": 2},
        {"text": REQUIREMENT_TEXT, "is_active": False},
    ]
)
def test_requirement_creation_validates_input(client, db, payload):
    email = f"req-validation-{uuid4().hex}@example.com"
    client_user = register(client, email, "client")
    freelancer = register(
        client,
        f"req-validation-free-{uuid4().hex}@example.com",
        "freelancer"
    )
    project = make_project(
        db,
        "Validation project",
        client_user["id"],
        freelancer["id"]
    )
    token = login_token(client, client_user["email"])

    response = client.post(
        f"/projects/{project.id}/requirements",
        json=payload,
        headers=auth_headers(token)
    )

    assert response.status_code == 422


def test_requirement_creation_requires_client_owner(client, db):
    client_a = create_user(db, "req-owner-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "req-owner-b@example.com", ROLE_CLIENT)
    freelancer = create_user(
        db,
        "req-owner-freelancer@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(db, "req-owner-reviewer@example.com", ROLE_REVIEWER)

    project = make_project(db, "Owner project", client_a.id, freelancer.id)
    finished = make_project(
        db,
        "Finished project",
        client_a.id,
        freelancer.id,
        status="completed"
    )

    for user in (freelancer, client_b, reviewer):
        token = login_token(client, user.email)
        response = create_requirement(client, token, project.id)
        assert response.status_code == 403

    owner_token = login_token(client, client_a.email)

    missing = create_requirement(client, owner_token, 999999)
    terminal = create_requirement(client, owner_token, finished.id)

    assert missing.status_code == 404
    assert terminal.status_code == 409


# ------------------------------------------------------------------- list

def test_requirement_listing_is_scoped_to_project_and_access(client, db):
    client_a = create_user(db, "list-req-client-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "list-req-client-b@example.com", ROLE_CLIENT)
    freelancer_a = create_user(
        db,
        "list-req-freelancer-a@example.com",
        ROLE_FREELANCER
    )
    freelancer_b = create_user(
        db,
        "list-req-freelancer-b@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(db, "list-req-reviewer@example.com", ROLE_REVIEWER)

    project_a = make_project(
        db,
        "Project A",
        client_a.id,
        freelancer_a.id
    )
    project_b = make_project(
        db,
        "Project B",
        client_b.id,
        freelancer_b.id
    )

    requirement_1 = make_requirement(db, project_a.id)
    requirement_2 = make_requirement(
        db,
        project_a.id,
        text="The website must load in under two seconds on mobile."
    )
    make_requirement(db, project_b.id)

    def list_for(user, project_id):
        token = login_token(client, user.email)
        return client.get(
            f"/projects/{project_id}/requirements",
            headers=auth_headers(token)
        )

    for user in (client_a, freelancer_a, reviewer):
        response = list_for(user, project_a.id)
        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == {
            requirement_1.id,
            requirement_2.id
        }

    assert list_for(client_b, project_a.id).status_code == 403
    assert list_for(freelancer_b, project_a.id).status_code == 403
    assert list_for(client_a, project_b.id).status_code == 403
    assert list_for(client_a, 999999).status_code == 404


# ----------------------------------------------------------------- detail

def test_requirement_detail_access_and_project_association(client, db):
    client_a = create_user(db, "detail-req-client-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "detail-req-client-b@example.com", ROLE_CLIENT)
    freelancer_a = create_user(
        db,
        "detail-req-freelancer-a@example.com",
        ROLE_FREELANCER
    )
    freelancer_b = create_user(
        db,
        "detail-req-freelancer-b@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(db, "detail-req-reviewer@example.com", ROLE_REVIEWER)

    project_a = make_project(
        db,
        "Detail project A",
        client_a.id,
        freelancer_a.id
    )
    project_b = make_project(
        db,
        "Detail project B",
        client_b.id,
        freelancer_b.id
    )
    requirement = make_requirement(db, project_a.id)

    def get_for(user, project_id, requirement_id):
        token = login_token(client, user.email)
        return client.get(
            f"/projects/{project_id}/requirements/{requirement_id}",
            headers=auth_headers(token)
        )

    assert get_for(client_a, project_a.id, requirement.id).status_code == 200
    assert get_for(
        freelancer_a,
        project_a.id,
        requirement.id
    ).status_code == 200
    assert get_for(reviewer, project_a.id, requirement.id).status_code == 200
    assert get_for(client_b, project_a.id, requirement.id).status_code == 403
    assert get_for(
        client_b,
        project_b.id,
        requirement.id
    ).status_code == 404
    assert get_for(client_a, project_a.id, 999999).status_code == 404


# ----------------------------------------------------------------- update

def test_client_can_update_requirement(client, db):
    client_user = register(client, "update-req-client@example.com", "client")
    freelancer = register(
        client,
        "update-req-freelancer@example.com",
        "freelancer"
    )
    project = make_project(
        db,
        "Update requirement project",
        client_user["id"],
        freelancer["id"]
    )
    token = login_token(client, client_user["email"])

    created = create_requirement(client, token, project.id)
    assert created.status_code == 201
    requirement_id = created.json()["id"]

    response = client.patch(
        f"/projects/{project.id}/requirements/{requirement_id}",
        json={
            "text": "The checkout must support card and wallet payments.",
            "category": "payments",
            "source_quote": "Section 4: wallet payments are required."
        },
        headers=auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == (
        "The checkout must support card and wallet payments."
    )
    assert body["category"] == "payments"

    partial = client.patch(
        f"/projects/{project.id}/requirements/{requirement_id}",
        json={"category": None},
        headers=auth_headers(token)
    )

    assert partial.status_code == 200
    assert partial.json()["category"] is None
    assert partial.json()["text"] == (
        "The checkout must support card and wallet payments."
    )

    db.expire_all()
    stored = db.get(Requirement, requirement_id)
    assert stored.source_quote == "Section 4: wallet payments are required."


def test_requirement_update_authorization(client, db):
    client_a = create_user(db, "update-req-owner-a@example.com", ROLE_CLIENT)
    client_b = create_user(db, "update-req-owner-b@example.com", ROLE_CLIENT)
    freelancer = create_user(
        db,
        "update-req-freelancer@example.com",
        ROLE_FREELANCER
    )
    reviewer = create_user(
        db,
        "update-req-reviewer@example.com",
        ROLE_REVIEWER
    )

    project = make_project(
        db,
        "Update authorization project",
        client_a.id,
        freelancer.id
    )
    finished = make_project(
        db,
        "Finished update project",
        client_a.id,
        freelancer.id,
        status="cancelled"
    )
    requirement = make_requirement(db, project.id)
    finished_requirement = make_requirement(db, finished.id)

    for user in (freelancer, client_b, reviewer):
        token = login_token(client, user.email)
        response = client.patch(
            f"/projects/{project.id}/requirements/{requirement.id}",
            json={"category": "unauthorized"},
            headers=auth_headers(token)
        )
        assert response.status_code == 403

    owner_token = login_token(client, client_a.email)

    missing = client.patch(
        f"/projects/{project.id}/requirements/999999",
        json={"category": "missing"},
        headers=auth_headers(owner_token)
    )
    terminal = client.patch(
        f"/projects/{finished.id}/requirements/{finished_requirement.id}",
        json={"category": "blocked"},
        headers=auth_headers(owner_token)
    )

    assert missing.status_code == 404
    assert terminal.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": None},
        {"text": "short"},
        {"project_id": 2},
        {"is_active": False},
    ]
)
def test_requirement_update_validates_input(client, db, payload):
    email = f"req-update-validation-{uuid4().hex}@example.com"
    client_user = register(client, email, "client")
    freelancer = register(
        client,
        f"req-update-free-{uuid4().hex}@example.com",
        "freelancer"
    )
    project = make_project(
        db,
        "Update validation project",
        client_user["id"],
        freelancer["id"]
    )
    requirement = make_requirement(db, project.id)
    token = login_token(client, client_user["email"])

    response = client.patch(
        f"/projects/{project.id}/requirements/{requirement.id}",
        json=payload,
        headers=auth_headers(token)
    )

    assert response.status_code == 422


# ------------------------------------------------------------------ misc

def test_requirement_endpoints_require_authentication(client):
    assert client.get(
        "/projects/1/requirements"
    ).status_code == 401
    assert client.get(
        "/projects/1/requirements/1"
    ).status_code == 401
    assert client.post(
        "/projects/1/requirements",
        json={"text": REQUIREMENT_TEXT}
    ).status_code == 401
    assert client.patch(
        "/projects/1/requirements/1",
        json={"category": "test"}
    ).status_code == 401


def test_requirements_are_returned_as_structured_ai_ready_payload(client, db):
    client_user = register(client, "ai-ready-client@example.com", "client")
    freelancer = register(
        client,
        "ai-ready-freelancer@example.com",
        "freelancer"
    )
    project = make_project(
        db,
        "AI ready project",
        client_user["id"],
        freelancer["id"]
    )
    token = login_token(client, client_user["email"])

    first = create_requirement(client, token, project.id)
    second = create_requirement(
        client,
        token,
        project.id,
        text="The website must load in under two seconds on mobile.",
        category="performance",
        source_quote="Section 5: mobile load time under two seconds."
    )

    assert first.status_code == 201
    assert second.status_code == 201

    response = client.get(
        f"/projects/{project.id}/requirements",
        headers=auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [
        first.json()["id"],
        second.json()["id"]
    ]

    for item in body:
        assert set(item) == {
            "id",
            "project_id",
            "text",
            "category",
            "source_quote"
        }
        assert isinstance(item["id"], int)
        assert item["project_id"] == project.id
        assert len(item["text"]) >= 10
