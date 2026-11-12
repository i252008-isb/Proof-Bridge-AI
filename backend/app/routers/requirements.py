from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Requirement, User
from app.schemas import (
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate
)
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role
)
from app.services.project_service import (
    ensure_project_access,
    ensure_project_mutable,
    ensure_project_owner,
    get_project_or_404
)
from app.services.requirement_service import get_requirement_or_404


router = APIRouter(
    prefix="/projects/{project_id}/requirements",
    tags=["Requirements"]
)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER
)

client_only = require_role(ROLE_CLIENT)


@router.post(
    "",
    response_model=RequirementResponse,
    status_code=status.HTTP_201_CREATED
)
def create_requirement(
    project_id: int,
    payload: RequirementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only)
):
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)
    ensure_project_mutable(project)

    requirement = Requirement(
        project_id=project.id,
        text=payload.text,
        category=payload.category,
        source_quote=payload.source_quote
    )

    db.add(requirement)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirement could not be created for this project."
        )

    db.refresh(requirement)

    return requirement


@router.get("", response_model=list[RequirementResponse])
def list_requirements(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return (
        db.query(Requirement)
        .filter(Requirement.project_id == project.id)
        .order_by(Requirement.id)
        .all()
    )


@router.get("/{requirement_id}", response_model=RequirementResponse)
def get_requirement(
    project_id: int,
    requirement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return get_requirement_or_404(db, project.id, requirement_id)


@router.patch("/{requirement_id}", response_model=RequirementResponse)
def update_requirement(
    project_id: int,
    requirement_id: int,
    payload: RequirementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only)
):
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)
    ensure_project_mutable(project)

    requirement = get_requirement_or_404(db, project.id, requirement_id)

    changes = payload.model_dump(exclude_unset=True)

    for field, value in changes.items():
        setattr(requirement, field, value)

    db.commit()
    db.refresh(requirement)

    return requirement
