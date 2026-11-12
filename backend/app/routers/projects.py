from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, User
from app.schemas import (
    ProjectCreate,
    ProjectResponse,
    ProjectStatusResponse,
    ProjectStatusUpdate,
    ProjectUpdate
)
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role
)
from app.services.project_service import (
    PROJECT_STATUS_CREATED,
    ensure_project_access,
    ensure_project_mutable,
    ensure_project_owner,
    get_project_or_404,
    record_status,
    set_project_status,
    status_history
)


router = APIRouter(
    prefix="/projects",
    tags=["Projects"]
)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER
)

client_only = require_role(ROLE_CLIENT)


def _status_response(
    db: Session,
    project: Project
) -> ProjectStatusResponse:
    return ProjectStatusResponse(
        project_id=project.id,
        status=project.status,
        history=status_history(db, project.id)
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED
)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only)
):
    freelancer = db.get(User, payload.freelancer_id)

    if freelancer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Freelancer not found."
        )

    if freelancer.role != ROLE_FREELANCER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assigned user must have the freelancer role."
        )

    project = Project(
        title=payload.title,
        description=payload.description,
        status=PROJECT_STATUS_CREATED,
        client_id=current_user.id,
        freelancer_id=freelancer.id,
        amount=payload.amount,
        currency=payload.currency or "USD",
    )

    db.add(project)

    try:
        db.flush()
        record_status(
            db,
            project.id,
            PROJECT_STATUS_CREATED,
            current_user.id,
            "Project created."
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Project could not be created because a referenced "
                "user no longer exists."
            )
        )

    db.refresh(project)

    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    query = db.query(Project)

    if current_user.role == ROLE_CLIENT:
        query = query.filter(Project.client_id == current_user.id)
    elif current_user.role == ROLE_FREELANCER:
        query = query.filter(Project.freelancer_id == current_user.id)

    return query.order_by(Project.id).all()


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only)
):
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)
    ensure_project_mutable(project)

    changes = payload.model_dump(exclude_unset=True)

    if "amount" in changes and changes["amount"] != project.amount:
        from app.models import PayPalTransaction
        paid_tx = (
            db.query(PayPalTransaction)
            .filter(
                PayPalTransaction.project_id == project.id,
                PayPalTransaction.status.in_(["PAID", "COMPLETED"]),
            )
            .first()
        )
        if paid_tx:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Amount cannot be changed once an order is paid."
            )

    for field, value in changes.items():
        setattr(project, field, value)

    record_status(
        db,
        project.id,
        project.status,
        current_user.id,
        "Project details updated."
    )

    db.commit()
    db.refresh(project)

    return project


@router.get(
    "/{project_id}/status",
    response_model=ProjectStatusResponse
)
def get_project_status(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return _status_response(db, project)


@router.patch(
    "/{project_id}/status",
    response_model=ProjectStatusResponse
)
def update_project_status(
    project_id: int,
    payload: ProjectStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only)
):
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)
    ensure_project_mutable(project)

    set_project_status(
        db,
        project,
        payload.status,
        current_user.id,
        payload.note
    )

    db.commit()
    db.refresh(project)

    return _status_response(db, project)
