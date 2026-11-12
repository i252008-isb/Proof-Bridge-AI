"""Authorized read-only case timeline."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import CaseHistoryResponse
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role,
)
from app.services.case_history_service import project_case_history
from app.services.project_service import (
    ensure_project_access,
    get_project_or_404,
)


router = APIRouter(
    prefix="/projects/{project_id}/history",
    tags=["Case History"],
)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
)


@router.get(
    "",
    response_model=CaseHistoryResponse,
    summary="Get the immutable case timeline",
)
def get_case_history(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return project_case_history(db, project)
