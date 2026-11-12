from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import CaseStatusLog, Project, User
from app.security import ROLE_REVIEWER


PROJECT_STATUS_CREATED = "created"
PROJECT_STATUS_IN_PROGRESS = "in_progress"
PROJECT_STATUS_UNDER_REVIEW = "under_review"
PROJECT_STATUS_COMPLETED = "completed"
PROJECT_STATUS_CANCELLED = "cancelled"

PROJECT_STATUSES = (
    PROJECT_STATUS_CREATED,
    PROJECT_STATUS_IN_PROGRESS,
    PROJECT_STATUS_UNDER_REVIEW,
    PROJECT_STATUS_COMPLETED,
    PROJECT_STATUS_CANCELLED,
)

ALLOWED_STATUS_TRANSITIONS = {
    PROJECT_STATUS_CREATED: frozenset({
        PROJECT_STATUS_IN_PROGRESS,
        PROJECT_STATUS_CANCELLED,
    }),
    PROJECT_STATUS_IN_PROGRESS: frozenset({
        PROJECT_STATUS_UNDER_REVIEW,
        PROJECT_STATUS_CANCELLED,
    }),
    PROJECT_STATUS_UNDER_REVIEW: frozenset({
        PROJECT_STATUS_COMPLETED,
        PROJECT_STATUS_IN_PROGRESS,
        PROJECT_STATUS_CANCELLED,
    }),
    PROJECT_STATUS_COMPLETED: frozenset(),
    PROJECT_STATUS_CANCELLED: frozenset(),
}

TERMINAL_PROJECT_STATUSES = frozenset({
    PROJECT_STATUS_COMPLETED,
    PROJECT_STATUS_CANCELLED,
})


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found."
        )

    return project


def ensure_project_access(project: Project, user: User) -> None:
    if user.role == ROLE_REVIEWER:
        return

    if user.id in {project.freelancer_id, project.client_id}:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this project."
    )


def ensure_project_owner(project: Project, user: User) -> None:
    if project.client_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project's client can modify it."
        )


def ensure_project_mutable(project: Project) -> None:
    if project.status in TERMINAL_PROJECT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Project in status '{project.status}' "
                "can no longer be modified."
            )
        )


def allowed_next_statuses(current_status: str) -> set[str]:
    return set(
        ALLOWED_STATUS_TRANSITIONS.get(current_status, frozenset())
    )


def record_status(
    db: Session,
    project_id: int,
    status_value: str,
    changed_by: int | None,
    note: str | None
) -> None:
    db.add(CaseStatusLog(
        project_id=project_id,
        status=status_value,
        note=note,
        changed_by=changed_by
    ))


def set_project_status(
    db: Session,
    project: Project,
    new_status: str,
    changed_by: int | None,
    reason: str | None = None
) -> CaseStatusLog:
    """Apply one validated status transition and append its audit entry.

    The caller must commit. History entries are append-only; no function in
    this module updates or deletes an existing ``CaseStatusLog`` row.
    """
    if new_status == project.status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project is already in status '{project.status}'."
        )

    allowed_statuses = allowed_next_statuses(project.status)

    if new_status not in allowed_statuses:
        allowed_text = ", ".join(sorted(allowed_statuses)) or "none"

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot change status from '{project.status}' to "
                f"'{new_status}'. Allowed next statuses: {allowed_text}."
            )
        )

    previous_status = project.status
    project.status = new_status

    log = CaseStatusLog(
        project_id=project.id,
        status=new_status,
        note=reason or (
            f"Status changed from '{previous_status}' to '{new_status}'."
        ),
        changed_by=changed_by
    )
    db.add(log)

    return log


def status_history(db: Session, project_id: int) -> list[CaseStatusLog]:
    return (
        db.query(CaseStatusLog)
        .filter(CaseStatusLog.project_id == project_id)
        .order_by(CaseStatusLog.id)
        .all()
    )
