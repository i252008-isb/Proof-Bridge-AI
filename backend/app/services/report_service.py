"""Project investigation reports derived from persisted AI analysis.

A report never runs the AI itself and never invents a finding. It copies
the stored requirement assessments, evidence inventory, contradictions,
and missing-information entries from one analysis snapshot, after checking
that the project's current requirements and evidence still match that
snapshot. Reports are advisory: a human reviewer makes the final decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Evidence, Project, Report, Requirement
from app.schemas import (
    ProjectReportContent,
    ProjectReportListResponse,
    ProjectReportResponse,
    ProjectReportSummary,
    ReportEvidenceReference,
    ReportHumanReviewRecommendation,
    ReportInconsistency,
    ReportMissingInformation,
    ReportObservedValue,
    ReportProjectInfo,
    ReportRequirementFinding,
)
from app.services.ai_analysis import (
    ensure_analysis_is_current,
    get_latest_project_analysis,
    get_project_analysis_report,
)


logger = logging.getLogger("proofbridge.reports")

REPORT_KIND = "project_investigation_report"
REPORT_SCHEMA_VERSION = "1.0"

_UNCERTAIN_STATUSES = frozenset({
    "partially_supported",
    "unverified",
    "insufficient_evidence",
})

_REVIEW_REASONS = {
    "supported": (
        "AI marked this requirement as supported; a human reviewer must "
        "still confirm the cited evidence."
    ),
    "partially_supported": (
        "AI marked this requirement as partially supported; a human "
        "reviewer should assess the remaining gaps."
    ),
    "unverified": (
        "AI could not verify this requirement; a human reviewer should "
        "assess the available evidence."
    ),
    "insufficient_evidence": (
        "AI found insufficient evidence for this requirement; a human "
        "reviewer should assess or request the missing evidence."
    ),
    "contradicted": (
        "AI found contradicting evidence for this requirement; a human "
        "reviewer must evaluate the inconsistency."
    ),
}


def generate_project_report(
    db: Session,
    project: Project,
    *,
    analysis_report_id: int | None = None,
) -> ProjectReportResponse:
    """Build and store a report from one analysis snapshot.

    Raises ``404`` when no analysis exists and ``409`` when requirements or
    evidence changed after the analysis was generated. Nothing is stored
    on either error.
    """
    analysis = (
        get_project_analysis_report(db, project.id, analysis_report_id)
        if analysis_report_id is not None
        else get_latest_project_analysis(db, project.id)
    )

    requirements = _load_requirements(db, project.id)
    evidence_rows = _load_evidence(db, project.id)
    ensure_analysis_is_current(
        analysis,
        requirements,
        evidence_rows,
        action="generating a report",
    )

    evidence_by_id = {evidence.id: evidence for evidence in evidence_rows}
    findings = _build_findings(analysis, requirements)
    evidence_inventory = _build_evidence_inventory(
        analysis, evidence_rows, evidence_by_id
    )
    inconsistencies = _build_inconsistencies(analysis, evidence_by_id)
    missing_information = [
        ReportMissingInformation(
            id=entry.id,
            description=entry.description,
            recommended_evidence=list(entry.recommended_evidence),
        )
        for entry in analysis.report.missing_information
    ]
    review_recommendations = [
        ReportHumanReviewRecommendation(
            requirement_id=finding.requirement_id,
            status=finding.status,
            reason=finding.human_review_reason,
        )
        for finding in findings
        if finding.requires_human_review
        and finding.human_review_reason is not None
    ]

    report_status = _report_status(
        analysis=analysis,
        findings=findings,
        evidence_inventory=evidence_inventory,
        inconsistencies=inconsistencies,
        missing_information=missing_information,
    )

    content = ProjectReportContent(
        schema_version=REPORT_SCHEMA_VERSION,
        status=report_status,
        project=ReportProjectInfo(
            project_id=project.id,
            title=project.title,
            description=project.description,
            status=project.status,
            client_id=project.client_id,
            freelancer_id=project.freelancer_id,
            created_at=project.created_at,
        ),
        analysis_report_id=analysis.report_id,
        analysis_generated_at=analysis.generated_at,
        ai_package_version=analysis.ai_package_version,
        generated_at=datetime.now(timezone.utc),
        human_review_required=True,
        final_decision_notice=analysis.final_decision_notice,
        requirement_findings=findings,
        evidence_inventory=evidence_inventory,
        missing_information=missing_information,
        inconsistencies=inconsistencies,
        uncertain_requirement_ids=[
            finding.requirement_id
            for finding in findings
            if finding.uncertain
        ],
        contradicted_requirement_ids=[
            finding.requirement_id
            for finding in findings
            if finding.status == "contradicted"
        ],
        missing_evidence_requirement_ids=[
            finding.requirement_id
            for finding in findings
            if finding.missing_evidence
        ],
        human_review_recommendations=review_recommendations,
        limitations=list(analysis.report.limitations),
        source_warnings=list(analysis.integration_warnings),
    )

    row = Report(project_id=project.id, content={})
    db.add(row)

    try:
        db.flush()
        row.content = content.model_dump(mode="json")
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(row)
    return _content_to_response(row)


def get_latest_project_report(
    db: Session, project_id: int
) -> ProjectReportResponse:
    rows = (
        db.query(Report)
        .filter(Report.project_id == project_id)
        .order_by(Report.id.desc())
        .all()
    )

    for row in rows:
        if _is_report_content(row.content):
            return _content_to_response(row)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No investigation report has been generated for this project.",
    )


def get_project_report(
    db: Session, project_id: int, report_id: int
) -> ProjectReportResponse:
    row = db.get(Report, report_id)

    if (
        row is None
        or row.project_id != project_id
        or not _is_report_content(row.content)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investigation report not found.",
        )

    return _content_to_response(row)


def list_project_reports(
    db: Session,
    project_id: int,
    *,
    limit: int,
    offset: int,
) -> ProjectReportListResponse:
    rows = (
        db.query(Report)
        .filter(Report.project_id == project_id)
        .order_by(Report.id.desc())
        .all()
    )
    reports = [
        row for row in rows if _is_report_content(row.content)
    ]
    items: list[ProjectReportSummary] = []

    for row in reports[offset:offset + limit]:
        try:
            items.append(_summary_for(row))
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            logger.error(
                "Stored report %s is unreadable and was omitted from the "
                "list: %s",
                row.id,
                type(exc).__name__,
            )

    return ProjectReportListResponse(
        items=items,
        total=len(reports),
        limit=limit,
        offset=offset,
    )


def _load_requirements(db: Session, project_id: int) -> list[Requirement]:
    return (
        db.query(Requirement)
        .filter(Requirement.project_id == project_id)
        .order_by(Requirement.id)
        .all()
    )


def _load_evidence(db: Session, project_id: int) -> list[Evidence]:
    return (
        db.query(Evidence)
        .filter(Evidence.project_id == project_id)
        .order_by(Evidence.id)
        .all()
    )


def _build_findings(
    analysis, requirements: list[Requirement]
) -> list[ReportRequirementFinding]:
    requirements_by_id = {
        requirement.id: requirement for requirement in requirements
    }

    findings: list[ReportRequirementFinding] = []

    for stored in analysis.requirement_findings:
        requirement = requirements_by_id[stored.requirement_id]
        missing_evidence = stored.status == "insufficient_evidence"
        uncertain = stored.status in _UNCERTAIN_STATUSES
        reason = (
            _REVIEW_REASONS[stored.status]
            if stored.requires_human_review
            else None
        )

        findings.append(
            ReportRequirementFinding(
                requirement_id=stored.requirement_id,
                requirement_text=requirement.text,
                status=stored.status,
                confidence=stored.confidence,
                rationale=stored.rationale,
                supporting_evidence_ids=list(
                    stored.supporting_evidence_ids
                ),
                contradicting_evidence_ids=list(
                    stored.contradicting_evidence_ids
                ),
                cited_evidence_ids=list(stored.cited_evidence_ids),
                missing_evidence=missing_evidence,
                uncertain=uncertain,
                requires_human_review=stored.requires_human_review,
                human_review_reason=reason,
            )
        )

    return findings


def _build_evidence_inventory(
    analysis,
    evidence_rows: list[Evidence],
    evidence_by_id: dict[int, Evidence],
) -> list[ReportEvidenceReference]:
    entries_by_id: dict[int, ReportEvidenceReference] = {}

    for entry in analysis.report.evidence_inventory:
        evidence_id = _backend_evidence_id(entry.evidence_id)
        _require_project_evidence(evidence_id, evidence_by_id)

        entries_by_id[evidence_id] = ReportEvidenceReference(
            evidence_id=evidence_id,
            filename=entry.filename,
            kind=entry.kind.value,
            status=entry.status.value,
            summary=entry.summary,
            needs_attention=entry.status.value in {
                "failed",
                "needs_review",
            },
            extraction_warning_codes=list(
                entry.extraction_warning_codes
            ),
        )

    for evidence in evidence_rows:
        if evidence.id in entries_by_id:
            continue

        entries_by_id[evidence.id] = ReportEvidenceReference(
            evidence_id=evidence.id,
            filename=evidence.filename,
            kind="other",
            status="unknown",
            summary=(
                "The stored analysis did not include an inventory entry "
                "for this evidence item."
            ),
            needs_attention=True,
        )

    return [entries_by_id[evidence.id] for evidence in evidence_rows]


def _build_inconsistencies(
    analysis,
    evidence_by_id: dict[int, Evidence],
) -> list[ReportInconsistency]:
    inconsistencies: list[ReportInconsistency] = []

    for contradiction in analysis.report.contradictions:
        evidence_ids = [
            _backend_evidence_id(raw_id)
            for raw_id in contradiction.evidence_ids
        ]
        for evidence_id in evidence_ids:
            _require_project_evidence(evidence_id, evidence_by_id)

        observed_values: list[ReportObservedValue] = []

        for observation in contradiction.observed_values:
            evidence_id = (
                _backend_evidence_id(observation.evidence_id)
                if observation.evidence_id is not None
                else None
            )
            if evidence_id is not None:
                _require_project_evidence(evidence_id, evidence_by_id)

            observed_values.append(
                ReportObservedValue(
                    value=observation.value,
                    source=observation.source,
                    evidence_id=evidence_id,
                )
            )

        inconsistencies.append(
            ReportInconsistency(
                id=contradiction.id,
                field=contradiction.field,
                description=contradiction.description,
                evidence_ids=list(dict.fromkeys(evidence_ids)),
                observed_values=observed_values,
            )
        )

    return inconsistencies


def _backend_evidence_id(raw_id: str) -> int:
    try:
        evidence_id = int(raw_id.removeprefix("evidence-"))
    except ValueError:
        evidence_id = -1

    if evidence_id < 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The stored AI analysis references evidence that cannot "
                "be matched to this project."
            ),
        )

    return evidence_id


def _require_project_evidence(
    evidence_id: int, evidence_by_id: dict[int, Evidence]
) -> None:
    if evidence_id not in evidence_by_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The stored AI analysis references evidence that does not "
                "belong to this project."
            ),
        )


def _report_status(
    *,
    analysis,
    findings: list[ReportRequirementFinding],
    evidence_inventory: list[ReportEvidenceReference],
    inconsistencies: list[ReportInconsistency],
    missing_information: list[ReportMissingInformation],
) -> str:
    if (
        analysis.status == "completed_with_warnings"
        or analysis.integration_warnings
        or inconsistencies
        or missing_information
        or any(entry.needs_attention for entry in evidence_inventory)
        or any(finding.missing_evidence or finding.uncertain for finding in findings)
    ):
        return "completed_with_warnings"

    return "completed"


def _summary_for(row: Report) -> ProjectReportSummary:
    content = ProjectReportContent.model_validate(row.content)
    findings = content.requirement_findings

    return ProjectReportSummary(
        report_id=row.id,
        project_id=row.project_id,
        status=content.status,
        generated_at=content.generated_at,
        created_at=row.created_at,
        analysis_report_id=content.analysis_report_id,
        ai_package_version=content.ai_package_version,
        requirement_count=len(findings),
        missing_evidence_count=len(
            content.missing_evidence_requirement_ids
        ),
        contradiction_count=len(content.inconsistencies),
        human_attention_count=sum(
            1 for finding in findings if finding.requires_human_review
        ),
    )


def _is_report_content(content) -> bool:
    return (
        isinstance(content, dict)
        and content.get("kind") == REPORT_KIND
        and content.get("schema_version") == REPORT_SCHEMA_VERSION
    )


def _content_to_response(row: Report) -> ProjectReportResponse:
    try:
        payload = dict(row.content or {})
        payload["report_id"] = row.id
        payload["created_at"] = row.created_at
        return ProjectReportResponse.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.error(
            "Stored investigation report %s is unreadable: %s",
            row.id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored investigation report is unreadable.",
        ) from exc
