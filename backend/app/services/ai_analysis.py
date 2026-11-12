"""Adapter between backend project records and the proofbridge_ai pipeline.

Person 3's AI module is used as-is. This module only:

1. translates ``Project``, ``Requirement``, and ``Evidence`` rows into the
   AI module's documented input models;
2. runs the module's real analysis and report pipeline;
3. validates every AI output with the module's own Pydantic models; and
4. stores the validated snapshot in the existing ``Report`` table.

It never implements a second AI pipeline, never decides a dispute, and
never approves or executes a payment or refund. Every stored result keeps
``human_review_required=True`` and the module's final-decision notice.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import threading

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import proofbridge_ai
from proofbridge_ai.config import Settings as AISettings
from proofbridge_ai.exceptions import (
    AnalysisError,
    ConfigurationError,
    DocumentExtractionError,
    FileTooLargeError,
    InputValidationError,
    OCRNotAvailableError,
    ProofBridgeAIError,
    ProviderError,
    ProviderResponseValidationError,
    ServiceNotImplementedError,
    UnsupportedFileTypeError,
)
from proofbridge_ai.integration.facade import ProofBridgeAIFacade, get_facade
from proofbridge_ai.schemas import (
    CaseContext,
    CaseEvent,
    ClaimAssessment,
    CustomerClaim,
    EvidenceInput,
    EvidenceInventoryStatus,
    EvidenceItem,
    EvidenceKind,
    EvidenceUpload,
    ExtractionWarning,
    InvestigationReport,
    SupportCaseAnalysisResult,
    SupportTicket,
)

from app.config import settings as backend_settings
from app.models import (
    AnalysisResult,
    CaseStatusLog,
    Evidence,
    Project,
    Report,
    Requirement,
)
from app.schemas import (
    AnalysisHistoryItem,
    AnalysisHistoryResponse,
    AnalysisInputSummary,
    ProjectAnalysisContent,
    ProjectAnalysisResponse,
    RequirementComparisonSummary,
    RequirementFinding,
)
from app.services.file_storage import resolve_stored_path


logger = logging.getLogger("proofbridge.ai_analysis")

ANALYSIS_KIND = "project_ai_analysis"
ANALYSIS_SCHEMA_VERSION = "1.1"
ACCEPTED_SCHEMA_VERSIONS = {"1.0", "1.1"}

_STATUS_ORDER = (
    "supported",
    "partially_supported",
    "unverified",
    "insufficient_evidence",
    "contradicted",
)

_PROJECT_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS: dict[int, threading.Lock] = {}


@dataclass(frozen=True)
class AnalysisRunOutcome:
    """One analysis request result and whether a new snapshot was created."""

    analysis: ProjectAnalysisResponse
    created: bool


def _project_lock(project_id: int) -> threading.Lock:
    with _PROJECT_LOCKS_GUARD:
        return _PROJECT_LOCKS.setdefault(project_id, threading.Lock())


_AI_ERROR_STATUS = (
    (OCRNotAvailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
    (FileTooLargeError, status.HTTP_413_CONTENT_TOO_LARGE),
    (UnsupportedFileTypeError, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE),
    (DocumentExtractionError, 422),
    (ProviderResponseValidationError, status.HTTP_502_BAD_GATEWAY),
    (ProviderError, status.HTTP_502_BAD_GATEWAY),
    (InputValidationError, status.HTTP_400_BAD_REQUEST),
    (ServiceNotImplementedError, status.HTTP_501_NOT_IMPLEMENTED),
    (ConfigurationError, status.HTTP_500_INTERNAL_SERVER_ERROR),
    (AnalysisError, status.HTTP_500_INTERNAL_SERVER_ERROR),
    (ProofBridgeAIError, status.HTTP_500_INTERNAL_SERVER_ERROR),
)


def get_ai_facade_dependency() -> ProofBridgeAIFacade:
    """Return the shared AI facade; tests override this dependency."""
    return get_facade()


def run_project_analysis(
    db: Session,
    project: Project,
    facade: ProofBridgeAIFacade | None = None,
    *,
    force: bool = False,
) -> AnalysisRunOutcome:
    """Run Person 3's pipeline for one project and persist the result.

    The caller must already have checked project authorization. The AI
    module receives only this project's requirements and evidence; stored
    files are read through the containment-checked storage helper.

    Identical requests are answered from the latest matching snapshot
    unless ``force`` is true. A per-project lock prevents two concurrent
    requests from running the same analysis twice in one process.
    """
    facade = facade or get_ai_facade_dependency()
    ai_settings = facade.settings

    with _project_lock(project.id):
        requirements = _load_requirements(db, project.id)
        evidence_rows = _load_evidence(db, project.id)
        status_logs = _load_status_logs(db, project.id)
        fingerprint = _input_fingerprint(
            project,
            requirements,
            evidence_rows,
            ai_settings,
        )

        if not force:
            reused = _find_reusable_report(db, project.id, fingerprint)
            if reused is not None:
                return AnalysisRunOutcome(analysis=reused, created=False)

        warnings: list[str] = []
        if not requirements:
            warnings.append(
                "No requirements are defined for this project; no "
                "requirement claims could be verified."
            )
        if not evidence_rows:
            warnings.append(
                "No evidence files are attached to this project; the "
                "analysis could only assess the project description."
            )

        ticket = _build_ticket(project, requirements, evidence_rows)
        case_context = _build_case_context(project, status_logs)
        uploads, skipped_ids = _load_uploads(
            evidence_rows, ai_settings, warnings
        )
        has_images = any(
            (upload.content_type or "").startswith("image/")
            for upload in uploads
        )
        if has_images and not ai_settings.ocr_enabled:
            warnings.append(
                "OCR is disabled; text embedded in image evidence will not "
                "be extracted. Visual analysis still runs. Enable OCR by "
                "setting PROOFBRIDGE_OCR_ENABLED=true and installing "
                "pytesseract plus the Tesseract engine."
            )

        try:
            _ensure_provider_configuration(ai_settings, has_images=has_images)
            processed_items, report_items, analysis_entries = (
                _process_evidence(facade, uploads, warnings)
            )
        except ProofBridgeAIError as exc:
            raise _http_error(exc) from exc

        report_items = _ordered_items(
            report_items + _skipped_items(evidence_rows, skipped_ids),
            evidence_rows,
        )

        try:
            analysis = asyncio.run(
                facade.analyze_support_case(
                    ticket,
                    analysis_entries,
                    refund_policy=None,
                    order_information=None,
                    case_context=case_context,
                )
            )
            report = facade.generate_investigation_report(
                analysis,
                ticket,
                evidence_items=report_items,
                order_information=None,
                payment_information=None,
                case_context=case_context,
            )
        except ProofBridgeAIError as exc:
            logger.warning(
                "AI analysis failed for project %s: %s",
                project.id,
                type(exc).__name__,
            )
            raise _http_error(exc) from exc

        try:
            findings, comparison = _build_requirement_findings(
                analysis=analysis,
                report=report,
                requirements=requirements,
                evidence_rows=evidence_rows,
            )
        except ValidationError as exc:
            logger.error(
                "AI requirement output failed validation for project %s: %s",
                project.id,
                type(exc).__name__,
            )
            raise _unexpected_output(
                "The AI module returned a requirement assessment with an "
                "invalid status or confidence value."
            ) from exc

        content = _build_content(
            project=project,
            ticket=ticket,
            analysis=analysis,
            report=report,
            processed_count=len(processed_items),
            requirements=requirements,
            evidence_rows=evidence_rows,
            skipped_ids=skipped_ids,
            warnings=warnings,
            ai_settings=ai_settings,
            has_images=has_images,
            fingerprint=fingerprint,
            findings=findings,
            comparison=comparison,
        )
        response = _persist_analysis(
            db=db,
            project=project,
            content=content,
            requirements=requirements,
            evidence_rows=evidence_rows,
            analysis=analysis,
        )
        return AnalysisRunOutcome(analysis=response, created=True)


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


def _load_status_logs(db: Session, project_id: int) -> list[CaseStatusLog]:
    return (
        db.query(CaseStatusLog)
        .filter(CaseStatusLog.project_id == project_id)
        .order_by(CaseStatusLog.id)
        .all()
    )


def _input_fingerprint(
    project: Project,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
    ai_settings: AISettings,
) -> str:
    """Hash exactly the inputs that can change an analysis result."""
    payload = {
        "project": {
            "id": project.id,
            "title": project.title,
            "description": project.description or "",
            "status": project.status,
            "created_at": project.created_at,
        },
        "requirements": [
            {
                "id": requirement.id,
                "text": requirement.text,
                "category": requirement.category,
                "source_quote": requirement.source_quote,
            }
            for requirement in requirements
        ],
        "evidence": [
            _evidence_fingerprint_entry(evidence)
            for evidence in evidence_rows
        ],
        "ai": {
            "package_version": getattr(
                proofbridge_ai, "__version__", "unknown"
            ),
            "demo_mode": ai_settings.demo_mode,
            "llm_provider": ai_settings.llm_provider,
            "embeddings_provider": ai_settings.embeddings_provider,
            "vision_provider": ai_settings.vision_provider,
            "ocr_enabled": ai_settings.ocr_enabled,
            "similarity_supported_threshold": (
                ai_settings.similarity_supported_threshold
            ),
            "similarity_partial_threshold": (
                ai_settings.similarity_partial_threshold
            ),
        },
        "backend_max_upload_bytes": backend_settings.MAX_UPLOAD_BYTES,
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _evidence_fingerprint_entry(evidence: Evidence) -> dict:
    size = None
    modified_ns = None

    try:
        stat = resolve_stored_path(evidence.stored_path).stat()
        size = stat.st_size
        modified_ns = stat.st_mtime_ns
    except (HTTPException, OSError):
        pass

    return {
        "id": evidence.id,
        "filename": evidence.filename,
        "mime_type": evidence.mime_type,
        "stored_path": evidence.stored_path,
        "size": size,
        "modified_ns": modified_ns,
    }


def _find_reusable_report(
    db: Session,
    project_id: int,
    fingerprint: str,
) -> ProjectAnalysisResponse | None:
    latest = (
        db.query(Report)
        .filter(Report.project_id == project_id)
        .order_by(Report.id.desc())
        .all()
    )

    for row in latest:
        content = row.content

        if not _is_analysis_content(content):
            continue

        if content.get("input_fingerprint") != fingerprint:
            return None

        try:
            return _content_to_response(row)
        except HTTPException:
            return None

    return None


def ensure_analysis_is_current(
    analysis: ProjectAnalysisResponse,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
    *,
    action: str = "continuing",
) -> None:
    """Reject an analysis snapshot whose inputs no longer match the project.

    An analysis is a point-in-time observation. Using it after its
    requirements or evidence changed would mix stale AI findings with
    current project data, so the caller must run a new analysis first.
    """
    findings = {
        finding.requirement_id: finding
        for finding in analysis.requirement_findings
    }
    current_ids = {requirement.id for requirement in requirements}

    if set(findings) != current_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The project requirements changed after this AI analysis. "
                f"Run a new analysis before {action}."
            ),
        )

    for requirement in requirements:
        if (
            findings[requirement.id].requirement_text.strip()
            != requirement.text.strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The project requirements changed after this AI "
                    f"analysis (requirement {requirement.id} differs). "
                    f"Run a new analysis before {action}."
                ),
            )

    analysed_evidence_ids = set(analysis.input_summary.evidence_ids)
    current_evidence_ids = {evidence.id for evidence in evidence_rows}

    if analysed_evidence_ids != current_evidence_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The project evidence changed after this AI analysis. "
                f"Run a new analysis before {action}."
            ),
        )


def get_latest_project_analysis(
    db: Session, project_id: int
) -> ProjectAnalysisResponse:
    """Return the newest stored AI analysis for a project."""
    rows = (
        db.query(Report)
        .filter(Report.project_id == project_id)
        .order_by(Report.id.desc())
        .all()
    )
    for row in rows:
        if _is_analysis_content(row.content):
            return _content_to_response(row)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No AI analysis report has been generated for this project.",
    )


def get_project_analysis_report(
    db: Session, project_id: int, report_id: int
) -> ProjectAnalysisResponse:
    """Return one stored AI analysis report, scoped to its project."""
    row = db.get(Report, report_id)

    if row is None or row.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis report not found.",
        )

    if not _is_analysis_content(row.content):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis report not found.",
        )

    return _content_to_response(row)


def list_project_analysis_history(
    db: Session,
    project_id: int,
    *,
    limit: int,
    offset: int,
) -> AnalysisHistoryResponse:
    """Return compact analysis history, newest first."""
    rows = (
        db.query(Report)
        .filter(Report.project_id == project_id)
        .order_by(Report.id.desc())
        .all()
    )

    analyses = [
        row for row in rows if _is_analysis_content(row.content)
    ]
    page = analyses[offset:offset + limit]
    items: list[AnalysisHistoryItem] = []

    for row in page:
        content = row.content

        try:
            items.append(_history_item(row, content))
        except (ValidationError, TypeError, ValueError) as exc:
            logger.error(
                "Stored analysis %s is unreadable and was omitted from "
                "history: %s",
                row.id,
                type(exc).__name__,
            )

    return AnalysisHistoryResponse(
        items=items,
        total=len(analyses),
        limit=limit,
        offset=offset,
    )


def _history_item(
    row: Report, content: dict
) -> AnalysisHistoryItem:
    input_summary = content.get("input_summary") or {}
    comparison = content.get("comparison") or {}

    return AnalysisHistoryItem(
        report_id=row.id,
        project_id=row.project_id,
        case_id=content["case_id"],
        status=content.get("status", "completed"),
        generated_at=content["generated_at"],
        created_at=row.created_at,
        ai_package_version=content["ai_package_version"],
        human_review_required=content["human_review_required"],
        input_fingerprint=content.get("input_fingerprint", ""),
        requirement_count=len(input_summary.get("requirement_ids", [])),
        evidence_count=len(input_summary.get("evidence_ids", [])),
        analysis_result_count=len(
            content.get("analysis_result_ids", [])
        ),
        supported_requirement_count=len(
            comparison.get("supported_requirement_ids", [])
        ),
        human_attention_requirement_count=len(
            comparison.get("human_attention_requirement_ids", [])
        ),
    )


# ------------------------------------------------- requirement comparison


def _build_requirement_findings(
    *,
    analysis: SupportCaseAnalysisResult,
    report: InvestigationReport,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
) -> tuple[list[RequirementFinding], RequirementComparisonSummary]:
    """Map Person 3's claim assessments back to project requirements.

    The function rejects rather than stores output that references a
    different project, omits a requirement, or duplicates an assessment.
    Statuses, confidence, rationale, and evidence references are copied
    from the AI output.
    """
    evidence_ids = {
        f"evidence-{evidence.id}": evidence.id
        for evidence in evidence_rows
    }
    requirement_ids = {requirement.id for requirement in requirements}
    claims_by_requirement: dict[int, ClaimAssessment] = {}

    for claim in analysis.claims:
        if not claim.claim_id.startswith("requirement-"):
            continue

        requirement_id = _requirement_id_from_claim_id(claim.claim_id)

        if requirement_id is None or requirement_id not in requirement_ids:
            raise _unexpected_output(
                "The AI module returned an assessment for a requirement "
                "that does not belong to this project."
            )

        if requirement_id in claims_by_requirement:
            raise _unexpected_output(
                "The AI module returned more than one assessment for "
                f"requirement {requirement_id}."
            )

        claims_by_requirement[requirement_id] = claim

    findings: list[RequirementFinding] = []

    for requirement in requirements:
        claim = claims_by_requirement.get(requirement.id)

        if claim is None:
            raise _unexpected_output(
                "The AI module did not return an assessment for "
                f"requirement {requirement.id}."
            )

        if claim.claim.strip() != requirement.text.strip():
            raise _unexpected_output(
                "The AI module returned text that does not match "
                f"requirement {requirement.id}."
            )

        _validate_similarity_scores(claim, evidence_ids)

        findings.append(
            RequirementFinding(
                requirement_id=requirement.id,
                requirement_text=requirement.text,
                status=claim.status.value,
                confidence=claim.confidence,
                rationale=claim.rationale,
                supporting_evidence_ids=_map_evidence_ids(
                    claim.supporting_evidence_ids, evidence_ids
                ),
                contradicting_evidence_ids=_map_evidence_ids(
                    claim.contradicting_evidence_ids, evidence_ids
                ),
                cited_evidence_ids=_map_evidence_ids(
                    [
                        passage.evidence_id
                        for passage in claim.cited_passages
                    ],
                    evidence_ids,
                ),
                analysis_method=claim.analysis_method,
                source_kind=claim.source_kind.value,
                requires_human_review=claim.requires_human_review,
            )
        )

    comparison = _comparison_summary(findings, report, evidence_ids)
    return findings, comparison


def _requirement_id_from_claim_id(claim_id: str) -> int | None:
    try:
        return int(claim_id.removeprefix("requirement-"))
    except ValueError:
        return None


def _validate_similarity_scores(claim, evidence_ids: dict[str, int]) -> None:
    _map_evidence_ids(
        [score.evidence_id for score in claim.similarity_scores],
        evidence_ids,
    )


def _map_evidence_ids(
    raw_ids: list[str], evidence_ids: dict[str, int]
) -> list[int]:
    mapped: list[int] = []

    for raw_id in raw_ids:
        evidence_id = evidence_ids.get(raw_id)

        if evidence_id is None:
            raise _unexpected_output(
                "The AI module referenced evidence that does not belong "
                "to this project."
            )

        if evidence_id not in mapped:
            mapped.append(evidence_id)

    return mapped


def _comparison_summary(
    findings: list[RequirementFinding],
    report: InvestigationReport,
    evidence_ids: dict[str, int],
) -> RequirementComparisonSummary:
    grouped: dict[str, list[int]] = {
        status: [] for status in _STATUS_ORDER
    }

    for finding in findings:
        grouped[finding.status].append(finding.requirement_id)

    uncertain = (
        grouped["partially_supported"]
        + grouped["unverified"]
        + grouped["insufficient_evidence"]
    )
    needs_attention = uncertain + grouped["contradicted"]
    evidence_attention = _evidence_needing_attention(
        report, evidence_ids
    )

    return RequirementComparisonSummary(
        verified_requirement_ids=list(grouped["supported"]),
        supported_requirement_ids=list(grouped["supported"]),
        partially_supported_requirement_ids=list(
            grouped["partially_supported"]
        ),
        unverified_requirement_ids=list(grouped["unverified"]),
        insufficient_evidence_requirement_ids=list(
            grouped["insufficient_evidence"]
        ),
        contradicted_requirement_ids=list(grouped["contradicted"]),
        missing_evidence_requirement_ids=list(
            grouped["insufficient_evidence"]
        ),
        uncertain_requirement_ids=uncertain,
        human_attention_requirement_ids=needs_attention,
        evidence_needing_attention_ids=evidence_attention,
    )


def _evidence_needing_attention(
    report: InvestigationReport,
    evidence_ids: dict[str, int],
) -> list[int]:
    ids = [
        entry.evidence_id
        for entry in report.evidence_inventory
        if entry.status.value in {"failed", "needs_review"}
    ]
    ids.extend(report.unresolved_evidence_ids)
    return _map_evidence_ids(ids, evidence_ids)


def _unexpected_output(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=message + " Nothing was stored.",
    )


# --------------------------------------------------------------- inputs


def _build_ticket(
    project: Project,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
) -> SupportTicket:
    complaint = (project.description or "").strip() or project.title
    claims = [
        CustomerClaim(
            id=f"requirement-{requirement.id}",
            claim=requirement.text,
            source="project_requirement",
        )
        for requirement in requirements
    ]

    return SupportTicket(
        case_id=f"project-{project.id}",
        complaint=complaint,
        product_name=project.title,
        requested_resolution="",
        claims=claims,
        customer_supplied_evidence_ids=[
            f"evidence-{evidence.id}" for evidence in evidence_rows
        ],
        metadata={
            "source": "proofbridge_project",
            "project_status": project.status,
        },
    )


def _build_case_context(
    project: Project, status_logs: list[CaseStatusLog]
) -> CaseContext:
    events = [
        CaseEvent(
            event_type="project_created",
            description=f"Project {project.id} was created.",
            timestamp=project.created_at,
        )
    ]

    for log in status_logs:
        note = f" Note: {log.note}" if log.note else ""
        events.append(
            CaseEvent(
                event_type="project_status_changed",
                description=f"Project status changed to {log.status}.{note}",
                timestamp=log.created_at,
            )
        )

    return CaseContext(
        case_id=f"project-{project.id}",
        title=project.title,
        description=project.description or "",
        created_at=project.created_at,
        events=events,
        metadata={"project_status": project.status},
    )


def _load_uploads(
    evidence_rows: list[Evidence],
    ai_settings: AISettings,
    warnings: list[str],
) -> tuple[list[EvidenceUpload], list[int]]:
    uploads: list[EvidenceUpload] = []
    skipped_ids: list[int] = []
    size_limit = min(
        ai_settings.max_file_size_bytes,
        backend_settings.MAX_UPLOAD_BYTES,
    )

    for evidence in evidence_rows:
        try:
            path = resolve_stored_path(evidence.stored_path)
            if path.stat().st_size > size_limit:
                warnings.append(
                    f"Evidence {evidence.id} ({evidence.filename!r}) exceeds "
                    "the configured analysis size limit and was skipped."
                )
                skipped_ids.append(evidence.id)
                continue
            data = path.read_bytes()
        except HTTPException:
            warnings.append(
                f"Evidence {evidence.id} ({evidence.filename!r}) could not be "
                "found in storage and was skipped."
            )
            skipped_ids.append(evidence.id)
            continue
        except OSError as exc:
            warnings.append(
                f"Evidence {evidence.id} ({evidence.filename!r}) could not be "
                f"read ({type(exc).__name__}) and was skipped."
            )
            skipped_ids.append(evidence.id)
            continue

        uploads.append(
            EvidenceUpload(
                evidence_input=EvidenceInput(
                    evidence_id=f"evidence-{evidence.id}",
                    filename=evidence.filename,
                    evidence_type="uploaded_evidence",
                    source="project_evidence",
                    uploaded_by=str(evidence.uploaded_by),
                    uploaded_at=evidence.created_at,
                    metadata={
                        "mime_type": (
                            evidence.mime_type or "application/octet-stream"
                        )
                    },
                ),
                file_bytes=data,
                content_type=evidence.mime_type,
            )
        )

    return uploads, skipped_ids


def _process_evidence(
    facade: ProofBridgeAIFacade,
    uploads: list[EvidenceUpload],
    warnings: list[str],
) -> tuple[
    list[EvidenceItem],
    list[EvidenceItem],
    list[EvidenceItem | EvidenceUpload],
]:
    """Extract evidence once and choose the right pipeline input per item.

    Processed items are reused for text evidence. Images are passed as raw
    uploads so the pipeline can run Person 3's vision service as well; the
    separately extracted item is still used for the report inventory.

    Files that fail extraction are represented in the report inventory by
    a ``FAILED`` item built from the module's own ``EvidenceItem`` schema,
    so the report never silently drops an uploaded file.
    """
    if not uploads:
        return [], [], []

    try:
        batch = facade.extract_evidence_batch(uploads)
    except ProofBridgeAIError as exc:
        raise _http_error(exc) from exc

    items = list(batch.items)
    by_id = {
        upload.evidence_input.evidence_id: upload for upload in uploads
    }
    failures = {
        failure.evidence_id: failure for failure in batch.failures
    }

    for failure in batch.failures:
        warnings.append(
            f"Evidence {failure.evidence_id!r} ({failure.filename!r}) could "
            f"not be processed ({failure.error_type}); the investigation "
            "continued with the remaining evidence."
        )

    report_items: list[EvidenceItem] = list(items)
    for evidence_id, failure in failures.items():
        upload = by_id.get(evidence_id)
        if upload is not None:
            report_items.append(_failed_item(upload, failure))

    entries: list[EvidenceItem | EvidenceUpload] = []
    for item in items:
        if item.kind is EvidenceKind.IMAGE:
            entries.append(by_id[item.evidence_id])
        else:
            entries.append(item)

    for evidence_id in failures:
        upload = by_id.get(evidence_id)
        if upload is not None:
            entries.append(upload)

    order = {
        upload.evidence_input.evidence_id: index
        for index, upload in enumerate(uploads)
    }
    entries.sort(key=lambda entry: order.get(_entry_id(entry), len(order)))
    report_items.sort(key=lambda item: order.get(item.evidence_id, len(order)))

    return items, report_items, entries


def _failed_item(upload: EvidenceUpload, failure) -> EvidenceItem:
    evidence_input = upload.evidence_input

    return EvidenceItem(
        evidence_id=evidence_input.evidence_id,
        filename=evidence_input.filename,
        kind=_kind_for(evidence_input.filename, upload.content_type),
        status=EvidenceInventoryStatus.FAILED,
        evidence_type=evidence_input.evidence_type,
        category=evidence_input.category,
        source=evidence_input.source,
        uploaded_by=evidence_input.uploaded_by,
        uploaded_at=evidence_input.uploaded_at,
        content_type=upload.content_type,
        summary=(
            "Evidence could not be processed by the AI pipeline; it is "
            "listed so the failed item remains visible to a human reviewer."
        ),
        extraction_warnings=[
            ExtractionWarning(
                code=failure.error_type,
                message=failure.message,
            )
        ],
        metadata=dict(evidence_input.metadata),
    )


def _skipped_items(
    evidence_rows: list[Evidence], skipped_ids: list[int]
) -> list[EvidenceItem]:
    skipped = set(skipped_ids)

    return [
        EvidenceItem(
            evidence_id=f"evidence-{evidence.id}",
            filename=evidence.filename,
            kind=_kind_for(evidence.filename, evidence.mime_type),
            status=EvidenceInventoryStatus.FAILED,
            source="project_evidence",
            uploaded_by=str(evidence.uploaded_by),
            uploaded_at=evidence.created_at,
            content_type=evidence.mime_type,
            summary=(
                "Evidence could not be read from backend storage; it was "
                "not analyzed."
            ),
            extraction_warnings=[
                ExtractionWarning(
                    code="storage_unavailable",
                    message=(
                        "The stored evidence file is missing or unreadable; "
                        "no content was supplied to the AI pipeline."
                    ),
                )
            ],
        )
        for evidence in evidence_rows
        if evidence.id in skipped
    ]


def _ordered_items(
    items: list[EvidenceItem], evidence_rows: list[Evidence]
) -> list[EvidenceItem]:
    order = {
        f"evidence-{evidence.id}": index
        for index, evidence in enumerate(evidence_rows)
    }
    return sorted(items, key=lambda item: order.get(item.evidence_id, len(order)))


def _kind_for(
    filename: str, content_type: str | None
) -> EvidenceKind:
    lowered = filename.lower()
    mime = (content_type or "").lower()

    if mime == "application/pdf" or lowered.endswith(".pdf"):
        return EvidenceKind.PDF
    if "wordprocessingml" in mime or lowered.endswith(".docx"):
        return EvidenceKind.DOCX
    if mime.startswith("image/") or lowered.endswith(
        (".png", ".jpg", ".jpeg", ".webp")
    ):
        return EvidenceKind.IMAGE
    if lowered.endswith((".txt", ".md", ".csv")):
        return EvidenceKind.TEXT
    return EvidenceKind.OTHER


def _entry_id(entry: EvidenceItem | EvidenceUpload) -> str:
    if isinstance(entry, EvidenceItem):
        return entry.evidence_id
    return entry.evidence_input.evidence_id


# ----------------------------------------------------------- configuration


def _ensure_provider_configuration(
    ai_settings: AISettings, *, has_images: bool
) -> None:
    """Fail clearly before any work if a real provider lacks credentials.

    Only environment variable names are reported; secret values are never
    read into an error message or log.
    """
    if ai_settings.demo_mode:
        return

    missing: list[str] = []

    if (
        ai_settings.llm_provider == "openai"
        and not ai_settings.llm_key_present()
    ):
        missing.append("PROOFBRIDGE_LLM_API_KEY")

    if (
        ai_settings.embeddings_provider == "openai"
        and not ai_settings.embeddings_key_present()
    ):
        missing.append("PROOFBRIDGE_EMBEDDINGS_API_KEY")

    if (
        has_images
        and ai_settings.vision_provider == "openai"
        and not ai_settings.vision_key_present()
    ):
        missing.append("PROOFBRIDGE_VISION_API_KEY")

    if missing:
        raise ConfigurationError(
            "External AI providers are configured but credentials are "
            "missing: "
            + ", ".join(missing)
            + ". Configure them, or set PROOFBRIDGE_DEMO_MODE=true to use "
            "the offline mock providers."
        )


def _provider_modes(
    ai_settings: AISettings, *, has_images: bool
) -> dict[str, str]:
    def mode(provider: str) -> str:
        if ai_settings.demo_mode or provider == "mock":
            return "mock"
        return provider

    return {
        "llm": mode(ai_settings.llm_provider),
        "embeddings": mode(ai_settings.embeddings_provider),
        "vision": mode(ai_settings.vision_provider) if has_images else "unused",
        "ocr": "enabled" if ai_settings.ocr_enabled else "disabled",
    }


def _external_processing(
    ai_settings: AISettings, *, has_images: bool
) -> bool:
    if ai_settings.demo_mode:
        return False

    return (
        ai_settings.llm_provider == "openai"
        or ai_settings.embeddings_provider == "openai"
        or (has_images and ai_settings.vision_provider == "openai")
    )


# -------------------------------------------------------------- validation


def _build_content(
    *,
    project: Project,
    ticket: SupportTicket,
    analysis: SupportCaseAnalysisResult,
    report: InvestigationReport,
    processed_count: int,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
    skipped_ids: list[int],
    warnings: list[str],
    ai_settings: AISettings,
    has_images: bool,
    fingerprint: str,
    findings: list[RequirementFinding],
    comparison: RequirementComparisonSummary,
) -> ProjectAnalysisContent:
    """Re-validate the AI outputs and build the stored envelope."""
    try:
        validated_analysis = SupportCaseAnalysisResult.model_validate(
            analysis.model_dump(mode="json")
        )
        validated_report = InvestigationReport.model_validate(
            report.model_dump(mode="json")
        )
    except ValidationError as exc:
        logger.error(
            "AI output failed schema validation for project %s: %s",
            project.id,
            type(exc).__name__,
        )
        raise _unexpected_output(
            "The AI module returned a result that failed its own schema "
            "validation."
        ) from exc

    if (
        not validated_analysis.requires_human_review
        or not validated_report.human_review_required
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The AI result was not marked for human review; it was "
                "rejected and nothing was stored."
            ),
        )

    if (
        validated_analysis.case_id != ticket.case_id
        or validated_report.case_id != ticket.case_id
    ):
        raise _unexpected_output(
            "The AI result did not match the requested project; it was "
            "rejected."
        )

    if any(
        not claim.requires_human_review
        for claim in validated_analysis.claims
    ):
        raise _unexpected_output(
            "The AI result contained a claim that was not marked for "
            "human review; it was rejected."
        )

    run_status = _run_status(
        warnings=warnings,
        skipped_ids=skipped_ids,
        report=validated_report,
        requirements=requirements,
        evidence_rows=evidence_rows,
    )

    return ProjectAnalysisContent(
        status=run_status,
        project_id=project.id,
        case_id=ticket.case_id,
        generated_at=validated_report.generated_at,
        ai_package_version=getattr(proofbridge_ai, "__version__", "unknown"),
        human_review_required=True,
        final_decision_notice=validated_report.final_decision_notice,
        provider_modes=_provider_modes(ai_settings, has_images=has_images),
        external_processing=_external_processing(
            ai_settings, has_images=has_images
        ),
        input_fingerprint=fingerprint,
        input_summary=AnalysisInputSummary(
            requirement_ids=[requirement.id for requirement in requirements],
            evidence_ids=[evidence.id for evidence in evidence_rows],
            skipped_evidence_ids=skipped_ids,
            evidence_files_processed=processed_count,
        ),
        integration_warnings=list(dict.fromkeys(warnings)),
        requirement_findings=findings,
        comparison=comparison,
        analysis=validated_analysis,
        report=validated_report,
    )


def _run_status(
    *,
    warnings: list[str],
    skipped_ids: list[int],
    report: InvestigationReport,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
) -> str:
    failed_inventory = any(
        entry.status in {
            EvidenceInventoryStatus.FAILED,
            EvidenceInventoryStatus.NEEDS_REVIEW,
        }
        for entry in report.evidence_inventory
    )

    if (
        warnings
        or skipped_ids
        or failed_inventory
        or not requirements
        or not evidence_rows
    ):
        return "completed_with_warnings"

    return "completed"


# -------------------------------------------------------------- persistence


def _persist_analysis(
    *,
    db: Session,
    project: Project,
    content: ProjectAnalysisContent,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
    analysis: SupportCaseAnalysisResult,
) -> ProjectAnalysisResponse:
    """Persist the snapshot and requirement rows in one transaction."""
    report = Report(project_id=project.id, content={})
    db.add(report)

    try:
        db.flush()

        rows = _build_analysis_rows(
            project=project,
            content=content,
            requirements=requirements,
            evidence_rows=evidence_rows,
            analysis=analysis,
            report_id=report.id,
        )
        db.add_all(rows)
        db.flush()

        content.analysis_result_ids = [row.id for row in rows]
        report.content = content.model_dump(mode="json")

        db.commit()
    except IntegrityError as exc:
        logger.warning(
            "Analysis persistence failed for project %s: %s",
            project.id,
            exc,
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AI analysis report could not be saved for this project.",
        )
    except Exception:
        db.rollback()
        raise

    db.refresh(report)
    return _content_to_response(report)


def _build_analysis_rows(
    *,
    project: Project,
    content: ProjectAnalysisContent,
    requirements: list[Requirement],
    evidence_rows: list[Evidence],
    analysis: SupportCaseAnalysisResult,
    report_id: int,
) -> list[AnalysisResult]:
    findings_by_requirement = {
        finding.requirement_id: finding
        for finding in content.requirement_findings
    }
    claims_by_requirement = {
        _requirement_id_from_claim_id(claim.claim_id): claim
        for claim in analysis.claims
        if claim.claim_id.startswith("requirement-")
    }
    evidence_ids = {
        f"evidence-{evidence.id}": evidence.id
        for evidence in evidence_rows
    }
    rows: list[AnalysisResult] = []

    for requirement in requirements:
        finding = findings_by_requirement.get(requirement.id)
        claim = claims_by_requirement.get(requirement.id)

        if finding is None or claim is None:
            raise _unexpected_output(
                "The AI module did not return a complete assessment for "
                f"requirement {requirement.id}."
            )

        similarity_evidence_ids = _map_evidence_ids(
            [score.evidence_id for score in claim.similarity_scores],
            evidence_ids,
        )
        referenced_evidence_ids = (
            finding.supporting_evidence_ids
            + finding.contradicting_evidence_ids
            + finding.cited_evidence_ids
            + similarity_evidence_ids
        )
        primary_evidence_id = (
            referenced_evidence_ids[0]
            if referenced_evidence_ids
            else None
        )
        similarity = max(
            (score.score for score in claim.similarity_scores),
            default=None,
        )
        claim_payload = claim.model_dump(mode="json")

        rows.append(
            AnalysisResult(
                project_id=project.id,
                requirement_id=requirement.id,
                evidence_id=primary_evidence_id,
                classification=finding.status,
                similarity=similarity,
                explanation=finding.rationale,
                status=finding.status,
                confidence=finding.confidence,
                report_id=report_id,
                details={
                    "report_id": report_id,
                    "requirement_text": requirement.text,
                    "status": finding.status,
                    "confidence": finding.confidence,
                    "rationale": finding.rationale,
                    "supporting_evidence_ids": (
                        finding.supporting_evidence_ids
                    ),
                    "contradicting_evidence_ids": (
                        finding.contradicting_evidence_ids
                    ),
                    "cited_evidence_ids": finding.cited_evidence_ids,
                    "claim_assessment": claim_payload,
                },
            )
        )

    return rows


def _is_analysis_content(content) -> bool:
    return (
        isinstance(content, dict)
        and content.get("kind") == ANALYSIS_KIND
        and content.get("schema_version") in ACCEPTED_SCHEMA_VERSIONS
    )


def _content_to_response(row: Report) -> ProjectAnalysisResponse:
    try:
        payload = dict(row.content or {})
        payload["report_id"] = row.id
        payload["created_at"] = row.created_at
        return ProjectAnalysisResponse.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.error(
            "Stored AI analysis report %s is unreadable: %s",
            row.id,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored AI analysis report is unreadable.",
        ) from exc


def _http_error(exc: ProofBridgeAIError) -> HTTPException:
    for error_type, status_code in _AI_ERROR_STATUS:
        if isinstance(exc, error_type):
            return HTTPException(
                status_code=status_code,
                detail=str(exc) or "AI analysis failed.",
            )

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="AI analysis failed.",
    )
