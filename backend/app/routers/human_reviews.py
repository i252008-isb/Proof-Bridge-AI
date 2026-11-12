"""Reviewer-only human review endpoints.

Review decisions are final case decisions made by humans. They are kept
separate from AI findings and never authorize payment or money movement.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    HumanReviewCreate,
    HumanReviewHistoryResponse,
    HumanReviewResponse,
    HumanReviewSubmissionResponse,
    PendingReviewListResponse,
    ReviewContextResponse,
)
from app.security import ROLE_REVIEWER, require_role
from app.services.human_review_service import (
    get_review,
    get_review_context,
    get_review_history,
    list_pending_reviews,
    submit_human_review,
)
from app.services.project_service import (
    ensure_project_access,
    get_project_or_404,
)


pending_router = APIRouter(
    prefix="/reviews",
    tags=["Human Review"],
)

router = APIRouter(
    prefix="/projects/{project_id}/reviews",
    tags=["Human Review"],
)

reviewer_only = require_role(ROLE_REVIEWER)


@pending_router.get(
    "/pending",
    response_model=PendingReviewListResponse,
    summary="List cases awaiting human review",
)
def get_pending_reviews(
    db: Session = Depends(get_db),
    current_user: User = Depends(reviewer_only),
):
    return list_pending_reviews(db)


@router.post(
    "",
    response_model=HumanReviewSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a human review decision",
)
def create_review(
    project_id: int,
    payload: HumanReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(reviewer_only),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return submit_human_review(db, project, current_user, payload)


@router.get(
    "/context",
    response_model=ReviewContextResponse,
    summary="View the evidence, analysis, and history for review",
)
def get_review_context_endpoint(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(reviewer_only),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_review_context(db, project)


@router.get(
    "",
    response_model=HumanReviewHistoryResponse,
    summary="List human review history",
)
def list_reviews(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(reviewer_only),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_review_history(db, project.id)


@router.get(
    "/{review_id}",
    response_model=HumanReviewResponse,
    summary="Get one human review",
)
def get_review_endpoint(
    project_id: int,
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(reviewer_only),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_review(db, project.id, review_id)
