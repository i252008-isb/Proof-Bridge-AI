"""Project investigation report endpoints.

Reports are stored snapshots derived from one persisted AI analysis. They
do not run the AI, do not alter case status, and never authorize payment.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    ProjectReportListResponse,
    ProjectReportResponse,
)
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role,
)
from app.services.project_service import (
    ensure_project_access,
    get_project_or_404,
)
from app.services.report_service import (
    generate_project_report,
    get_latest_project_report,
    get_project_report,
    list_project_reports,
)


router = APIRouter(
    prefix="/projects/{project_id}/reports",
    tags=["Reports"],
)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
)


@router.post(
    "",
    response_model=ProjectReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an investigation report",
)
def create_report(
    project_id: int,
    analysis_report_id: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Stored analysis snapshot to use. Defaults to the latest one."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    """Generate a report from stored AI analysis and current project data.

    Returns **409** when requirements or evidence changed after the
    selected analysis, so a report never mixes stale findings with newer
    project data.
    """
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return generate_project_report(
        db,
        project,
        analysis_report_id=analysis_report_id,
    )


@router.get(
    "/latest",
    response_model=ProjectReportResponse,
    summary="Get the latest investigation report",
)
def get_latest_report(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_latest_project_report(db, project.id)


@router.get(
    "",
    response_model=ProjectReportListResponse,
    summary="List investigation reports",
)
def list_reports(
    project_id: int,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return list_project_reports(
        db,
        project.id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{report_id}",
    response_model=ProjectReportResponse,
    summary="Get one investigation report",
)
def get_report(
    project_id: int,
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_project_report(db, project.id, report_id)
