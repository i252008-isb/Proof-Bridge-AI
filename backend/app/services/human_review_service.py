"""Human review workflow.

Only reviewers submit decisions. Reviews are append-only: this module
never updates or deletes an existing ``HumanReview`` row. A decision is
recorded as a separate human artifact and is never merged into the AI
findings. Review decisions concern fulfillment verification only; they do
not authorize or execute a payment, refund, transfer, or release.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Evidence,
    HumanReview,
    Project,
    Requirement,
    User,
)
from app.schemas import (
    EvidenceResponse,
    HumanReviewCreate,
    HumanReviewHistoryResponse,
    HumanReviewResponse,
    HumanReviewSubmissionResponse,
    PendingReviewItem,
    PendingReviewListResponse,
    ProjectResponse,
    ProjectStatusEntry,
    ReviewContextResponse,
)
from app.services.ai_analysis import (
    ensure_analysis_is_current,
    get_latest_project_analysis,
)
from app.services.project_service import (
    PROJECT_STATUS_COMPLETED,
    PROJECT_STATUS_IN_PROGRESS,
    PROJECT_STATUS_UNDER_REVIEW,
    PROJECT_STATUS_CANCELLED,
    set_project_status,
    status_history,
)


logger = logging.getLogger("proofbridge.human_reviews")

REVIEW_DECISION_PROJECT_STATUS = {
    "verified": PROJECT_STATUS_COMPLETED,
    "partially_verified": PROJECT_STATUS_COMPLETED,
    "rejected": PROJECT_STATUS_CANCELLED,
    "needs_more_evidence": PROJECT_STATUS_IN_PROGRESS,
}


def submit_human_review(
    db: Session,
    project: Project,
    reviewer: User,
    payload: HumanReviewCreate,
) -> HumanReviewSubmissionResponse:
    """Record an immutable reviewer decision and its status transition."""
    project = (
        db.query(Project)
        .filter(Project.id == project.id)
        .with_for_update()
        .one()
    )
    analysis = get_latest_project_analysis(db, project.id)
    requirements = (
        db.query(Requirement)
        .filter(Requirement.project_id == project.id)
        .order_by(Requirement.id)
        .all()
    )
    evidence_rows = (
        db.query(Evidence)
        .filter(Evidence.project_id == project.id)
        .order_by(Evidence.id)
        .all()
    )
    ensure_analysis_is_current(
        analysis,
        requirements,
        evidence_rows,
        action="submitting a human review",
    )

    if project.status != PROJECT_STATUS_UNDER_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A human review can only be submitted while the project is "
                f"in status '{PROJECT_STATUS_UNDER_REVIEW}'. The current "
                f"status is '{project.status}'."
            ),
        )

    next_status = REVIEW_DECISION_PROJECT_STATUS[payload.decision]

    review = HumanReview(
        project_id=project.id,
        reviewer_id=reviewer.id,
        decision=payload.decision,
        notes=payload.notes,
    )
    db.add(review)

    try:
        db.flush()
        set_project_status(
            db,
            project,
            next_status,
            reviewer.id,
            f"Human review decision '{payload.decision}' recorded.",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The human review could not be saved for this project.",
        )
    except Exception:
        db.rollback()
        raise

    db.refresh(review)

    return HumanReviewSubmissionResponse(
        review=HumanReviewResponse.model_validate(review),
        project_status=project.status,
    )


def get_review_history(
    db: Session, project_id: int
) -> HumanReviewHistoryResponse:
    rows = _review_rows(db, project_id)

    return HumanReviewHistoryResponse(
        project_id=project_id,
        items=[
            HumanReviewResponse.model_validate(row) for row in rows
        ],
        total=len(rows),
    )


def get_review(
    db: Session, project_id: int, review_id: int
) -> HumanReviewResponse:
    row = db.get(HumanReview, review_id)

    if row is None or row.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Human review not found.",
        )

    return HumanReviewResponse.model_validate(row)


def list_pending_reviews(db: Session) -> PendingReviewListResponse:
    """Return cases awaiting review.

    A project appears when it is ``under_review`` and has an AI analysis.
    Every submitted decision moves the project out of ``under_review``, so
    a reviewed case disappears automatically; if the client later returns
    it to review, it reappears for a new decision.
    """
    projects = (
        db.query(Project)
        .filter(Project.status == PROJECT_STATUS_UNDER_REVIEW)
        .order_by(Project.id)
        .all()
    )
    items: list[PendingReviewItem] = []

    for project in projects:
        try:
            analysis = get_latest_project_analysis(db, project.id)
        except HTTPException:
            continue

        items.append(
            PendingReviewItem(
                project_id=project.id,
                title=project.title,
                status=project.status,
                latest_analysis_report_id=analysis.report_id,
                analysis_generated_at=analysis.generated_at,
                requirement_count=len(
                    analysis.input_summary.requirement_ids
                ),
                evidence_count=len(
                    analysis.input_summary.evidence_ids
                ),
                human_attention_requirement_count=len(
                    analysis.comparison.human_attention_requirement_ids
                ),
                project_created_at=project.created_at,
            )
        )

    items.sort(
        key=lambda item: item.analysis_generated_at,
        reverse=True,
    )

    return PendingReviewListResponse(items=items, total=len(items))


def get_review_context(
    db: Session, project: Project
) -> ReviewContextResponse:
    analysis = get_latest_project_analysis(db, project.id)
    evidence_rows = (
        db.query(Evidence)
        .filter(Evidence.project_id == project.id)
        .order_by(Evidence.id)
        .all()
    )

    return ReviewContextResponse(
        project=ProjectResponse.model_validate(project),
        latest_analysis=analysis,
        evidence=[
            EvidenceResponse.model_validate(row) for row in evidence_rows
        ],
        status_history=[
            ProjectStatusEntry.model_validate(row)
            for row in status_history(db, project.id)
        ],
        reviews=[
            HumanReviewResponse.model_validate(row)
            for row in _review_rows(db, project.id)
        ],
    )


def _review_rows(db: Session, project_id: int) -> list[HumanReview]:
    return (
        db.query(HumanReview)
        .filter(HumanReview.project_id == project_id)
        .order_by(HumanReview.id)
        .all()
    )
