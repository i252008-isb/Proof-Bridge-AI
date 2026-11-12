import io
import zipfile
from uuid import uuid4

import pymupdf

import proofbridge_ai

from app.config import settings
from app.main import app
from app.models import (
    AnalysisResult,
    Evidence,
    HumanReview,
    PayPalTransaction,
    Project,
    Report,
    Requirement,
    User,
)
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    hash_password,
)
from app.services.ai_analysis import get_ai_facade_dependency
from proofbridge_ai.config import Settings as AISettings
from proofbridge_ai.exceptions import ProviderError
from proofbridge_ai.integration.facade import ProofBridgeAIFacade


PASSWORD = "correct-password-123"

RECOMMENDATION_OUTCOMES = {
    "refund_recommended",
    "request_more_information",
    "escalate_to_human",
    "refund_not_supported_by_provided_policy",
    "alternative_resolution_suggested",
    "insufficient_policy_information",
}

VERIFICATION_STATUSES = {
    "supported",
    "partially_supported",
    "contradicted",
    "unverified",
    "insufficient_evidence",
}


def unique_email(prefix):
    return f"{prefix}-{uuid4().hex}@example.com"


def create_user(db, prefix, role):
    user = User(
        name="AI Test User",
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


def corrupt_docx_bytes():
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")

    return buffer.getvalue()


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


class _CountingFacade:
    def __init__(self, base):
        self.base = base
        self.settings = base.settings
        self.evidence_calls = 0
        self.analysis_calls = 0
        self.report_calls = 0

    def extract_evidence_batch(self, uploads):
        self.evidence_calls += 1
        return self.base.extract_evidence_batch(uploads)

    async def analyze_support_case(self, *args, **kwargs):
        self.analysis_calls += 1
        return await self.base.analyze_support_case(*args, **kwargs)

    def generate_investigation_report(self, *args, **kwargs):
        self.report_calls += 1
        return self.base.generate_investigation_report(*args, **kwargs)


class _UnexpectedOutputFacade:
    def __init__(self, base):
        self.base = base
        self.settings = base.settings

    def extract_evidence_batch(self, uploads):
        return self.base.extract_evidence_batch(uploads)

    async def analyze_support_case(self, *args, **kwargs):
        return await self.base.analyze_support_case(*args, **kwargs)

    def generate_investigation_report(self, *args, **kwargs):
        report = self.base.generate_investigation_report(*args, **kwargs)
        report.case_id = "project-999999"
        return report


# ------------------------------------------------------------ success path


def test_client_can_run_analysis_and_participants_can_read(client, db):
    owner = create_user(db, "ai-owner", ROLE_CLIENT)
    freelancer = create_user(db, "ai-freelancer", ROLE_FREELANCER)
    reviewer = create_user(db, "ai-reviewer", ROLE_REVIEWER)
    project = make_project(
        db, "Landing page delivery", owner.id, freelancer.id
    )
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
        filename="receipt.pdf",
        content_type="application/pdf",
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()["id"]

    owner_token = login_token(client, owner.email)
    response = run_analysis(client, owner_token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["report_id"] > 0
    assert body["project_id"] == project.id
    assert body["case_id"] == f"project-{project.id}"
    assert body["kind"] == "project_ai_analysis"
    assert body["schema_version"] == "1.1"
    assert body["status"] == "completed"
    assert body["ai_package_version"] == proofbridge_ai.__version__
    assert body["human_review_required"] is True
    assert body["final_decision_notice"]
    assert body["input_fingerprint"]
    assert len(body["input_fingerprint"]) == 64
    assert body["provider_modes"]["llm"] == "mock"
    assert body["provider_modes"]["embeddings"] == "mock"
    assert body["provider_modes"]["ocr"] == "disabled"
    assert body["external_processing"] is False
    assert body["input_summary"]["requirement_ids"] == [requirement.id]
    assert body["input_summary"]["evidence_ids"] == [evidence_id]
    assert body["input_summary"]["evidence_files_processed"] == 1

    claim = body["analysis"]["claims"][0]
    assert claim["claim_id"] == f"requirement-{requirement.id}"
    assert claim["claim"] == requirement.text
    assert claim["source"] == "project_requirement"
    assert claim["status"] in VERIFICATION_STATUSES
    assert claim["requires_human_review"] is True

    finding = body["requirement_findings"][0]
    assert finding["requirement_id"] == requirement.id
    assert finding["requirement_text"] == requirement.text
    assert finding["status"] == claim["status"]
    assert finding["confidence"] == claim["confidence"]
    assert finding["rationale"] == claim["rationale"]
    assert finding["requires_human_review"] is True
    assert isinstance(finding["cited_evidence_ids"], list)
    assert all(
        isinstance(item, int)
        for item in finding["supporting_evidence_ids"]
    )

    comparison = body["comparison"]
    assert requirement.id in (
        comparison["supported_requirement_ids"]
        + comparison["partially_supported_requirement_ids"]
        + comparison["unverified_requirement_ids"]
        + comparison["insufficient_evidence_requirement_ids"]
        + comparison["contradicted_requirement_ids"]
    )
    assert comparison["verified_requirement_ids"] == (
        comparison["supported_requirement_ids"]
    )

    inventory = body["report"]["evidence_inventory"]
    assert [entry["evidence_id"] for entry in inventory] == [
        f"evidence-{evidence_id}"
    ]
    assert inventory[0]["filename"] == "receipt.pdf"
    assert inventory[0]["summary"]
    assert inventory[0]["status"] == "processed"

    assert body["report"]["human_review_required"] is True
    assert body["report"]["final_decision_notice"]
    assert body["report"]["recommended_outcome"] in RECOMMENDATION_OUTCOMES
    assert len(body["report"]["supporting_findings"]) == 1
    assert any(
        "mock" in limitation.lower()
        for limitation in body["report"]["limitations"]
    )

    latest = client.get(
        f"/projects/{project.id}/analysis",
        headers=auth_headers(freelancer_token),
    )
    assert latest.status_code == 200, latest.text
    assert latest.json()["report_id"] == body["report_id"]

    reviewer_token = login_token(client, reviewer.email)
    specific = client.get(
        f"/projects/{project.id}/analysis/{body['report_id']}",
        headers=auth_headers(reviewer_token),
    )
    assert specific.status_code == 200, specific.text
    assert specific.json()["report_id"] == body["report_id"]

    stored = db.query(Report).one()
    assert stored.project_id == project.id
    assert stored.content["kind"] == "project_ai_analysis"
    assert stored.content["analysis"]["case_id"] == f"project-{project.id}"

    row = db.query(AnalysisResult).one()
    assert body["analysis_result_ids"] == [row.id]
    assert row.project_id == project.id
    assert row.requirement_id == requirement.id
    assert row.evidence_id in (None, evidence_id)
    assert row.classification == claim["status"]
    assert row.status == claim["status"]
    assert row.confidence == claim["confidence"]
    assert row.explanation == claim["rationale"]
    assert row.report_id == body["report_id"]
    assert row.created_at is not None
    assert row.details["claim_assessment"]["claim_id"] == claim["claim_id"]
    assert row.details["requirement_text"] == requirement.text
    assert row.details["supporting_evidence_ids"] == (
        finding["supporting_evidence_ids"]
    )


def test_repeated_analysis_reuses_matching_snapshot(client, db):
    owner = create_user(db, "ai-snapshot-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-snapshot-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Snapshot project", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)
    counter = _CountingFacade(
        ProofBridgeAIFacade(AISettings(demo_mode=True))
    )
    app.dependency_overrides[get_ai_facade_dependency] = lambda: counter

    first = run_analysis(client, token, project.id)
    second = run_analysis(client, token, project.id)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json()["report_id"] == first.json()["report_id"]
    assert db.query(Report).count() == 1
    assert counter.analysis_calls == 1
    assert counter.report_calls == 1

    forced = run_analysis(client, token, project.id, force=True)
    assert forced.status_code == 201, forced.text
    assert forced.json()["report_id"] != first.json()["report_id"]
    assert db.query(Report).count() == 2
    assert counter.analysis_calls == 2

    latest = client.get(
        f"/projects/{project.id}/analysis", headers=auth_headers(token)
    )
    assert latest.status_code == 200
    assert latest.json()["report_id"] == forced.json()["report_id"]

    make_requirement(
        db,
        project.id,
        "Include a contact form that sends email notifications.",
    )
    changed = run_analysis(client, token, project.id)
    assert changed.status_code == 201, changed.text
    assert changed.json()["report_id"] != forced.json()["report_id"]
    assert db.query(Report).count() == 3
    assert counter.analysis_calls == 3


def test_analysis_history_is_paginated_and_newest_first(client, db):
    owner = create_user(db, "ai-history-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-history-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "History project", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)

    first = run_analysis(client, token, project.id, force=True)
    second = run_analysis(client, token, project.id, force=True)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    history = client.get(
        f"/projects/{project.id}/analysis/history",
        headers=auth_headers(token),
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["total"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["report_id"] for item in body["items"]] == [
        second.json()["report_id"],
        first.json()["report_id"],
    ]

    item = body["items"][0]
    assert item["project_id"] == project.id
    assert item["status"] == "completed_with_warnings"
    assert item["human_review_required"] is True
    assert item["input_fingerprint"]
    assert item["analysis_result_count"] == 0

    page = client.get(
        f"/projects/{project.id}/analysis/history?limit=1&offset=1",
        headers=auth_headers(token),
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 2
    assert page.json()["limit"] == 1
    assert page.json()["offset"] == 1
    assert [entry["report_id"] for entry in page.json()["items"]] == [
        first.json()["report_id"]
    ]


# ---------------------------------------------------------- authorization


def test_unrelated_users_cannot_run_or_read_analysis(client, db):
    owner = create_user(db, "ai-private-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-private-freelancer", ROLE_FREELANCER
    )
    outsider_client = create_user(db, "ai-outsider-client", ROLE_CLIENT)
    outsider_freelancer = create_user(
        db, "ai-outsider-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Private analysis project", owner.id, freelancer.id
    )
    owner_token = login_token(client, owner.email)
    run = run_analysis(client, owner_token, project.id)
    assert run.status_code == 201, run.text
    report_id = run.json()["report_id"]

    for outsider in (outsider_client, outsider_freelancer):
        token = login_token(client, outsider.email)
        headers = auth_headers(token)

        assert run_analysis(client, token, project.id).status_code == 403
        assert (
            client.get(
                f"/projects/{project.id}/analysis", headers=headers
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/projects/{project.id}/analysis/{report_id}",
                headers=headers,
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/projects/{project.id}/analysis/history",
                headers=headers,
            ).status_code
            == 403
        )

    unauthenticated = client.post(f"/projects/{project.id}/analysis")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "unauthorized"


def test_analysis_report_is_scoped_to_its_project(client, db):
    owner = create_user(db, "ai-scope-owner", ROLE_CLIENT)
    freelancer = create_user(db, "ai-scope-freelancer", ROLE_FREELANCER)
    first = make_project(db, "First project", owner.id, freelancer.id)
    second = make_project(db, "Second project", owner.id, freelancer.id)
    token = login_token(client, owner.email)

    run = run_analysis(client, token, first.id)
    assert run.status_code == 201, run.text
    report_id = run.json()["report_id"]

    response = client.get(
        f"/projects/{second.id}/analysis/{report_id}",
        headers=auth_headers(token),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    latest = client.get(
        f"/projects/{second.id}/analysis", headers=auth_headers(token)
    )
    assert latest.status_code == 404


def test_analysis_only_uses_the_requested_projects_evidence(client, db):
    owner = create_user(db, "ai-isolation-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-isolation-freelancer", ROLE_FREELANCER
    )
    reviewed_project = make_project(
        db, "Reviewed project", owner.id, freelancer.id
    )
    other_project = make_project(
        db, "Other project", owner.id, freelancer.id
    )
    freelancer_token = login_token(client, freelancer.email)

    upload = upload_evidence(
        client,
        freelancer_token,
        other_project.id,
        receipt_pdf_bytes(),
        filename="other-receipt.pdf",
    )
    assert upload.status_code == 201, upload.text
    other_evidence_id = upload.json()["id"]

    owner_token = login_token(client, owner.email)
    response = run_analysis(client, owner_token, reviewed_project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["input_summary"]["evidence_ids"] == []
    assert body["input_summary"]["evidence_files_processed"] == 0
    assert body["report"]["evidence_inventory"] == []
    assert f"evidence-{other_evidence_id}" not in response.text


# ------------------------------------------------------- degraded inputs


def test_project_without_requirements_or_evidence_is_honest(client, db):
    owner = create_user(db, "ai-empty-owner", ROLE_CLIENT)
    freelancer = create_user(db, "ai-empty-freelancer", ROLE_FREELANCER)
    project = make_project(
        db, "Empty project", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)

    response = run_analysis(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    # With no backend requirements, Person 3's ticket analyzer derives its
    # own unverified claim from the project description.
    assert body["analysis"]["claims"]
    assert all(
        claim["claim_id"].startswith("claim-")
        for claim in body["analysis"]["claims"]
    )
    assert all(
        claim["source"] == "customer_ticket"
        for claim in body["analysis"]["claims"]
    )
    assert body["report"]["evidence_inventory"] == []
    assert body["input_summary"]["requirement_ids"] == []
    assert body["input_summary"]["evidence_ids"] == []
    assert body["status"] == "completed_with_warnings"
    assert body["requirement_findings"] == []
    assert body["comparison"]["human_attention_requirement_ids"] == []
    assert body["analysis_result_ids"] == []
    assert db.query(AnalysisResult).count() == 0
    assert any(
        "No requirements" in warning
        for warning in body["integration_warnings"]
    )
    assert any(
        "No evidence" in warning
        for warning in body["integration_warnings"]
    )
    assert body["human_review_required"] is True
    assert body["report"]["recommended_outcome"] in RECOMMENDATION_OUTCOMES


def test_evidence_can_support_a_requirement(client, db):
    owner = create_user(db, "ai-supported-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-supported-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Supported requirement project", owner.id, freelancer.id
    )
    requirement = make_requirement(
        db,
        project.id,
        "The purchase date 2026-11-01 must match the receipt.",
    )
    freelancer_token = login_token(client, freelancer.email)
    upload = upload_evidence(
        client,
        freelancer_token,
        project.id,
        receipt_pdf_bytes(),
        filename="receipt.pdf",
        content_type="application/pdf",
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()["id"]

    token = login_token(client, owner.email)
    response = run_analysis(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    finding = body["requirement_findings"][0]
    assert finding["requirement_id"] == requirement.id
    assert finding["status"] == "supported"
    assert body["comparison"]["verified_requirement_ids"] == [
        requirement.id
    ]
    assert body["comparison"]["supported_requirement_ids"] == [
        requirement.id
    ]
    assert requirement.id not in (
        body["comparison"]["human_attention_requirement_ids"]
    )

    row = db.query(AnalysisResult).one()
    assert row.requirement_id == requirement.id
    assert row.evidence_id == evidence_id
    assert row.status == "supported"
    assert row.similarity is not None
    assert row.details["supporting_evidence_ids"] == []


def test_requirement_without_evidence_is_reported_as_missing(client, db):
    owner = create_user(db, "ai-noev-owner", ROLE_CLIENT)
    freelancer = create_user(db, "ai-noev-freelancer", ROLE_FREELANCER)
    project = make_project(
        db, "No evidence project", owner.id, freelancer.id
    )
    requirement = make_requirement(
        db,
        project.id,
        "Deliver a responsive landing page with a contact form.",
    )
    token = login_token(client, owner.email)

    response = run_analysis(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    finding = body["requirement_findings"][0]
    assert finding["requirement_id"] == requirement.id
    assert finding["status"] == "insufficient_evidence"
    assert finding["supporting_evidence_ids"] == []
    assert finding["contradicting_evidence_ids"] == []
    assert body["comparison"]["missing_evidence_requirement_ids"] == [
        requirement.id
    ]
    assert body["comparison"]["insufficient_evidence_requirement_ids"] == [
        requirement.id
    ]
    assert requirement.id in (
        body["comparison"]["human_attention_requirement_ids"]
    )
    assert body["status"] == "completed_with_warnings"

    row = db.query(AnalysisResult).one()
    assert row.requirement_id == requirement.id
    assert row.evidence_id is None
    assert row.status == "insufficient_evidence"
    assert row.classification == "insufficient_evidence"


def test_missing_stored_file_is_skipped_not_fatal(client, db):
    owner = create_user(db, "ai-missing-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-missing-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Missing file project", owner.id, freelancer.id
    )
    make_requirement(
        db,
        project.id,
        "Deliver a responsive landing page with a contact form.",
    )
    evidence = Evidence(
        project_id=project.id,
        uploaded_by=freelancer.id,
        filename="gone.pdf",
        stored_path="evidence/999/deadbeef.pdf",
        mime_type="application/pdf",
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    token = login_token(client, owner.email)
    response = run_analysis(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["input_summary"]["skipped_evidence_ids"] == [evidence.id]
    assert any(
        "could not be found in storage" in warning
        for warning in body["integration_warnings"]
    )
    inventory = body["report"]["evidence_inventory"]
    assert [entry["evidence_id"] for entry in inventory] == [
        f"evidence-{evidence.id}"
    ]
    assert inventory[0]["status"] == "failed"
    assert "storage_unavailable" in inventory[0]["extraction_warning_codes"]
    assert (
        f"evidence-{evidence.id}"
        in body["report"]["unresolved_evidence_ids"]
    )
    assert body["comparison"]["evidence_needing_attention_ids"] == [
        evidence.id
    ]
    assert db.query(AnalysisResult).count() == 1
    assert body["analysis_result_ids"]


def test_corrupt_evidence_is_isolated(client, db):
    owner = create_user(db, "ai-corrupt-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-corrupt-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Corrupt evidence project", owner.id, freelancer.id
    )
    make_requirement(
        db,
        project.id,
        "Deliver a responsive landing page with a contact form.",
    )

    freelancer_token = login_token(client, freelancer.email)
    upload = upload_evidence(
        client,
        freelancer_token,
        project.id,
        corrupt_docx_bytes(),
        filename="broken.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()["id"]

    owner_token = login_token(client, owner.email)
    response = run_analysis(client, owner_token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert any(
        "could not be processed" in warning
        for warning in body["integration_warnings"]
    )
    assert body["input_summary"]["evidence_files_processed"] == 0
    inventory = body["report"]["evidence_inventory"]
    assert [entry["evidence_id"] for entry in inventory] == [
        f"evidence-{evidence_id}"
    ]
    assert inventory[0]["status"] == "failed"
    assert (
        f"evidence-{evidence_id}"
        in body["report"]["unresolved_evidence_ids"]
    )
    assert body["comparison"]["evidence_needing_attention_ids"] == [
        evidence_id
    ]
    assert body["status"] == "completed_with_warnings"
    row = db.query(AnalysisResult).one()
    assert row.evidence_id is None
    assert row.status in VERIFICATION_STATUSES
    assert row.details["claim_assessment"]["claim_id"].startswith(
        "requirement-"
    )
    assert body["human_review_required"] is True
    assert body["report"]["recommended_outcome"] in RECOMMENDATION_OUTCOMES


# ------------------------------------------------------------ error paths


class _FailingFacade:
    def __init__(self, ai_settings):
        self.settings = ai_settings

    def extract_evidence_batch(self, uploads):
        raise AssertionError("No evidence is expected in this test.")

    async def analyze_support_case(self, *args, **kwargs):
        raise ProviderError(
            "upstream provider failed.",
            provider="fake-provider",
        )


def test_provider_failure_maps_to_bad_gateway_envelope(client, db):
    owner = create_user(db, "ai-provider-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-provider-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Provider failure project", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)

    app.dependency_overrides[get_ai_facade_dependency] = (
        lambda: _FailingFacade(AISettings(demo_mode=True))
    )

    response = run_analysis(client, token, project.id)
    assert response.status_code == 502, response.text
    body = response.json()
    assert body["error"]["code"] == "bad_gateway"
    assert "upstream provider failed" in body["error"]["message"]
    assert db.query(Report).count() == 0
    assert db.query(AnalysisResult).count() == 0


def test_unexpected_model_output_is_rejected_without_persistence(
    client, db
):
    owner = create_user(db, "ai-unexpected-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-unexpected-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Unexpected output project", owner.id, freelancer.id
    )
    make_requirement(
        db,
        project.id,
        "Deliver a responsive landing page with a contact form.",
    )
    token = login_token(client, owner.email)
    base = ProofBridgeAIFacade(AISettings(demo_mode=True))
    app.dependency_overrides[get_ai_facade_dependency] = (
        lambda: _UnexpectedOutputFacade(base)
    )

    response = run_analysis(client, token, project.id)
    assert response.status_code == 502, response.text
    body = response.json()
    assert body["error"]["code"] == "bad_gateway"
    assert "did not match the requested project" in body["error"]["message"]
    assert db.query(Report).count() == 0
    assert db.query(AnalysisResult).count() == 0


def test_missing_external_credentials_are_reported_without_secrets(
    client, db
):
    owner = create_user(db, "ai-config-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-config-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Configuration project", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)

    ai_settings = AISettings(
        demo_mode=False,
        llm_provider="openai",
        llm_api_key="",
        embeddings_provider="mock",
        vision_provider="mock",
    )
    app.dependency_overrides[get_ai_facade_dependency] = (
        lambda: ProofBridgeAIFacade(ai_settings)
    )

    response = run_analysis(client, token, project.id)
    assert response.status_code == 500, response.text
    body = response.json()
    assert body["error"]["code"] == "internal_server_error"
    assert "PROOFBRIDGE_LLM_API_KEY" in body["error"]["message"]
    assert "PROOFBRIDGE_DEMO_MODE" in body["error"]["message"]
    assert db.query(Report).count() == 0
    assert db.query(AnalysisResult).count() == 0


# -------------------------------------------------------------- boundaries


def test_response_does_not_expose_stored_paths(client, db):
    owner = create_user(db, "ai-path-owner", ROLE_CLIENT)
    freelancer = create_user(db, "ai-path-freelancer", ROLE_FREELANCER)
    project = make_project(
        db, "Path privacy project", owner.id, freelancer.id
    )
    freelancer_token = login_token(client, freelancer.email)
    upload = upload_evidence(
        client,
        freelancer_token,
        project.id,
        receipt_pdf_bytes(),
        filename="receipt.pdf",
    )
    assert upload.status_code == 201, upload.text
    evidence = db.get(Evidence, upload.json()["id"])
    assert evidence is not None

    owner_token = login_token(client, owner.email)
    response = run_analysis(client, owner_token, project.id)
    assert response.status_code == 201, response.text

    assert evidence.stored_path not in response.text
    assert settings.upload_dir.as_posix() not in response.text


def test_analysis_never_creates_payment_or_human_review_records(client, db):
    owner = create_user(db, "ai-safety-owner", ROLE_CLIENT)
    freelancer = create_user(
        db, "ai-safety-freelancer", ROLE_FREELANCER
    )
    project = make_project(
        db, "Safety boundary project", owner.id, freelancer.id
    )
    token = login_token(client, owner.email)

    response = run_analysis(client, token, project.id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["human_review_required"] is True
    assert body["report"]["human_review_required"] is True
    assert body["final_decision_notice"] == (
        body["report"]["final_decision_notice"]
    )
    assert db.query(PayPalTransaction).count() == 0
    assert db.query(HumanReview).count() == 0
    assert db.query(Report).count() == 1
    assert db.query(AnalysisResult).count() == 0
