from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Requirement


def get_requirement_or_404(
    db: Session,
    project_id: int,
    requirement_id: int
) -> Requirement:
    requirement = db.get(Requirement, requirement_id)

    if requirement is None or requirement.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requirement not found."
        )

    return requirement
