"""Read-only case timeline assembled from immutable audit records."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CaseStatusLog, HumanReview, Project, Report
from app.schemas import CaseHistoryResponse, CaseTimelineEvent
from app.services.ai_analysis import ANALYSIS_KIND
from app.services.report_service import REPORT_KIND


def project_case_history(
    db: Session, project: Project
) -> CaseHistoryResponse:
    events: list[CaseTimelineEvent] = []

    for log in (
        db.query(CaseStatusLog)
        .filter(CaseStatusLog.project_id == project.id)
        .order_by(CaseStatusLog.id)
        .all()
    ):
        events.append(
            CaseTimelineEvent(
                event_type="status",
                occurred_at=log.created_at,
                actor_id=log.changed_by,
                summary=log.note or f"Case status: {log.status}.",
                status=log.status,
                reference_id=log.id,
            )
        )

    for row in (
        db.query(Report)
        .filter(Report.project_id == project.id)
        .order_by(Report.id)
        .all()
    ):
        kind = (row.content or {}).get("kind")

        if kind == ANALYSIS_KIND:
            events.append(
                CaseTimelineEvent(
                    event_type="analysis",
                    occurred_at=row.created_at,
                    summary=(
                        f"AI analysis snapshot {row.id} was generated. "
                        "It is advisory and requires human review."
                    ),
                    reference_id=row.id,
                )
            )
        elif kind == REPORT_KIND:
            events.append(
                CaseTimelineEvent(
                    event_type="report",
                    occurred_at=row.created_at,
                    summary=(
                        f"Investigation report {row.id} was generated "
                        "from a stored AI analysis snapshot."
                    ),
                    reference_id=row.id,
                )
            )

    for review in (
        db.query(HumanReview)
        .filter(HumanReview.project_id == project.id)
        .order_by(HumanReview.id)
        .all()
    ):
        events.append(
            CaseTimelineEvent(
                event_type="human_review",
                occurred_at=review.created_at,
                actor_id=review.reviewer_id,
                summary=(
                    "A human reviewer recorded decision "
                    f"'{review.decision}'."
                ),
                reference_id=review.id,
            )
        )

    events.sort(key=lambda event: event.occurred_at)

    return CaseHistoryResponse(
        project_id=project.id,
        current_status=project.status,
        events=events,
    )
