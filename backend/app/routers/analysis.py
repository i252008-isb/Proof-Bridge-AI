"""Project-scoped AI analysis endpoints.

HTTP concerns live here; the actual AI work is delegated to Person 3's
pipeline through ``app.services.ai_analysis``. Analysis is decision
support only: every response repeats that a human must make the final
decision, and no endpoint approves or executes a payment or refund.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import AnalysisHistoryResponse, ProjectAnalysisResponse
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role,
)
from app.services.ai_analysis import (
    get_ai_facade_dependency,
    get_latest_project_analysis,
    get_project_analysis_report,
    list_project_analysis_history,
    run_project_analysis,
)
from app.services.project_service import (
    ensure_project_access,
    get_project_or_404,
)
from proofbridge_ai.integration.facade import ProofBridgeAIFacade


router = APIRouter(
    prefix="/projects/{project_id}/analysis",
    tags=["AI Analysis"],
)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
)


@router.post(
    "",
    response_model=ProjectAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run evidence analysis for a project",
)
def run_analysis(
    project_id: int,
    response: Response,
    force: bool = Query(
        default=False,
        description=(
            "Run again even when the latest snapshot matches the current "
            "project inputs."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
    facade: ProofBridgeAIFacade = Depends(get_ai_facade_dependency),
):
    """Compare this project's requirements and evidence with Person 3's AI.

    Returns **201** for a new snapshot and **200** when the latest snapshot
    already matches the current inputs. Use ``force=true`` to create a new
    snapshot anyway.
    """
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    outcome = run_project_analysis(
        db,
        project,
        facade=facade,
        force=force,
    )

    if not outcome.created:
        response.status_code = status.HTTP_200_OK

    return outcome.analysis


@router.get(
    "",
    response_model=ProjectAnalysisResponse,
    summary="Get the latest analysis snapshot",
)
def get_latest_analysis(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    """Return the newest complete analysis snapshot for this project."""
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_latest_project_analysis(db, project.id)


@router.get(
    "/history",
    response_model=AnalysisHistoryResponse,
    summary="List analysis history",
)
def get_analysis_history(
    project_id: int,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    """Return compact analysis history, newest first."""
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return list_project_analysis_history(
        db,
        project.id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{report_id}",
    response_model=ProjectAnalysisResponse,
    summary="Get one analysis snapshot",
)
def get_analysis_report(
    project_id: int,
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader),
):
    """Return one snapshot only when it belongs to this project."""
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_project_analysis_report(db, project.id, report_id)
