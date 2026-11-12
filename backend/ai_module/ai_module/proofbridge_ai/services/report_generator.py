"""Structured investigation report generation.

The report copies findings from the analysis stage verbatim — it never
edits, reinterprets, or summarizes away warnings, contradictions, or
limitations. The timeline is built exclusively from supplied timestamps
(ticket dates, evidence upload times, backend case events); timestamps are
never invented. The neutral summary is a deterministic composition and is
labeled ``generation_method="heuristic"``.

If generation fails on unexpected data, a deterministic fallback report is
produced that preserves the underlying structured findings.
"""

from __future__ import annotations

from collections.abc import Sequence

from proofbridge_ai.config import Settings, get_settings
from proofbridge_ai.exceptions import InputValidationError
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.schemas import (
    CaseContext,
    CustomerClaim,
    EvidenceItem,
    InvestigationReport,
    OcrFinding,
    OrderInformation,
    PaymentInformation,
    PolicySummary,
    RecommendationOutcome,
    ReportEvidenceEntry,
    ReportTimelineEvent,
    SupportCaseAnalysisResult,
    SupportCaseOverview,
    SupportTicket,
    VerificationStatus,
)
from proofbridge_ai.services.text_normalizer import truncate_text

logger = get_logger("services.report_generator")

_OCR_EXCERPT_CHARS = 300
_RULE_SUMMARY_CHARS = 200


def generate_investigation_report(
    analysis: SupportCaseAnalysisResult,
    support_ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem] = (),
    order_information: OrderInformation | None = None,
    payment_information: PaymentInformation | None = None,
    case_context: CaseContext | None = None,
    settings: Settings | None = None,
) -> InvestigationReport:
    """Build the structured investigation report for one case.

    Args:
        analysis: Result of ``analyze_support_case``.
        support_ticket: The original backend-supplied ticket.
        evidence_items: Processed evidence items for the inventory.
        order_information: Backend order-system data (verbatim).
        payment_information: Payment-provider data (verbatim, informational).
        case_context: Backend case context (events feed the timeline).
        settings: Optional Settings override (tests).

    Returns:
        InvestigationReport — always ``human_review_required=True`` with
        the final-decision notice. On unexpected generation failure a
        fallback report preserving the structured findings is returned.
    """
    settings = settings or get_settings()
    if not isinstance(analysis, SupportCaseAnalysisResult):
        raise InputValidationError("analysis must be a SupportCaseAnalysisResult")
    if not isinstance(support_ticket, SupportTicket):
        raise InputValidationError("support_ticket must be a SupportTicket")
    try:
        return _build_report(
            analysis,
            support_ticket,
            evidence_items,
            order_information,
            payment_information,
            case_context,
        )
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "Report generation failed (%s); producing fallback report",
            type(exc).__name__,
        )
        return _fallback_report(
            analysis,
            support_ticket,
            evidence_items,
            order_information,
            payment_information,
            case_context,
            type(exc).__name__,
        )


def _build_report(
    analysis: SupportCaseAnalysisResult,
    ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem],
    order_information: OrderInformation | None,
    payment_information: PaymentInformation | None,
    case_context: CaseContext | None,
) -> InvestigationReport:
    items = [item for item in evidence_items if isinstance(item, EvidenceItem)]
    created_at = case_context.created_at if case_context else None
    recommendation = analysis.recommendation
    policy_summary = _policy_summary(analysis)
    claims = _claim_copies(analysis)
    status_counts = {
        status: sum(
            1 for assessment in analysis.claims if assessment.status is status
        )
        for status in VerificationStatus
        if any(assessment.status is status for assessment in analysis.claims)
    }
    return InvestigationReport(
        case_id=analysis.case_id,
        case_overview=SupportCaseOverview(
            case_id=analysis.case_id,
            issue_type=analysis.issue_type,
            product_name=ticket.product_name,
            requested_resolution=analysis.requested_resolution,
            complaint_summary=analysis.customer_claim_summary,
            created_at=created_at,
        ),
        customer_complaint=ticket.complaint,
        product_information=_product_information(ticket, order_information),
        requested_resolution=analysis.requested_resolution,
        customer_claims=claims,
        purchase_and_order_information=analysis.purchase_information,
        order_information=order_information,
        payment_information=payment_information,
        evidence_inventory=[_inventory_entry(item) for item in items],
        ocr_findings=[_ocr_finding(item) for item in items if item.ocr_applied],
        visual_analysis=analysis.visual_analysis,
        conversation_analysis=analysis.conversation_analysis,
        refund_policy_summary=policy_summary,
        cross_source_verification=analysis.cross_source_findings,
        supporting_findings=analysis.claims,
        contradictions=analysis.contradictions,
        missing_information=analysis.missing_information,
        policy_assessment=analysis.policy_evaluation,
        recommended_outcome=(
            recommendation.outcome
            if recommendation
            else RecommendationOutcome.INSUFFICIENT_POLICY_INFORMATION
        ),
        recommendation_reasoning=recommendation.reasoning if recommendation else "",
        recommendation=recommendation,
        evidence_references=[
            f"{item.evidence_id} — {item.filename}" for item in items
        ],
        timeline=_timeline(ticket, items, case_context),
        neutral_summary=_neutral_summary(analysis, len(items)),
        limitations=analysis.limitations,
        human_review_required=True,
        status_counts=status_counts,
        unresolved_evidence_ids=[
            item.evidence_id
            for item in items
            if item.status.value in {"needs_review", "failed"}
        ],
        source_summary=analysis.source_summary,
        generation_method="heuristic",
    )


def _claim_copies(analysis: SupportCaseAnalysisResult) -> list[CustomerClaim]:
    return [
        CustomerClaim(
            id=assessment.claim_id,
            claim=assessment.claim,
            source=assessment.source,
            verification_status=assessment.status,
            supporting_evidence_ids=assessment.supporting_evidence_ids,
            contradicting_evidence_ids=assessment.contradicting_evidence_ids,
            rationale=assessment.rationale,
        )
        for assessment in analysis.claims
    ]


def _policy_summary(analysis: SupportCaseAnalysisResult) -> PolicySummary | None:
    evaluation = analysis.policy_evaluation
    if evaluation is None or evaluation.policy_id is None:
        return None
    rule_summaries: list[str] = []
    for assessment in evaluation.rule_assessments:
        summary, _ = truncate_text(assessment.condition, _RULE_SUMMARY_CHARS)
        rule_summaries.append(summary)
    return PolicySummary(
        policy_id=evaluation.policy_id,
        policy_name=evaluation.policy_name or "",
        rule_count=len(evaluation.rule_assessments),
        rule_summaries=rule_summaries,
        extraction_warnings=[
            warning.message for warning in evaluation.warnings
        ],
    )


def _product_information(
    ticket: SupportTicket, order_information: OrderInformation | None
) -> str:
    name = ticket.product_name
    if not name and order_information:
        name = order_information.product_name
    if not name:
        return ""
    if order_information and order_information.product_model:
        return f"Product: {name} (model {order_information.product_model})"
    return f"Product: {name}"


def _inventory_entry(item: EvidenceItem) -> ReportEvidenceEntry:
    return ReportEvidenceEntry(
        evidence_id=item.evidence_id,
        filename=item.filename,
        kind=item.kind,
        status=item.status,
        category=item.category,
        evidence_type=item.evidence_type,
        uploaded_by=item.uploaded_by,
        uploaded_at=item.uploaded_at,
        summary=item.summary,
        identified_facts=item.identified_facts,
        extraction_warning_codes=[
            warning.code for warning in item.extraction_warnings
        ],
    )


def _ocr_finding(item: EvidenceItem) -> OcrFinding:
    excerpt, _ = truncate_text(item.extracted_text, _OCR_EXCERPT_CHARS)
    return OcrFinding(
        evidence_id=item.evidence_id,
        filename=item.filename,
        text_excerpt=excerpt,
        warnings=[warning.code for warning in item.extraction_warnings],
    )


def _timeline(
    ticket: SupportTicket,
    items: list[EvidenceItem],
    case_context: CaseContext | None,
) -> list[ReportTimelineEvent]:
    events: list[ReportTimelineEvent] = []
    if ticket.purchase_date:
        events.append(
            ReportTimelineEvent(
                event_type="purchase_date",
                description="Purchase date stated in the customer ticket.",
                timestamp=ticket.purchase_date,
                source="customer_ticket",
            )
        )
    if ticket.delivery_date:
        events.append(
            ReportTimelineEvent(
                event_type="delivery_date",
                description="Delivery date stated in the customer ticket.",
                timestamp=ticket.delivery_date,
                source="customer_ticket",
            )
        )
    for item in items:
        if item.uploaded_at:
            events.append(
                ReportTimelineEvent(
                    event_type="evidence_uploaded",
                    description=f"Evidence {item.evidence_id!r} "
                    f"({item.filename}) was uploaded.",
                    timestamp=item.uploaded_at,
                    source=f"evidence:{item.evidence_id}",
                )
            )
    if case_context:
        for event in case_context.events:
            events.append(
                ReportTimelineEvent(
                    event_type=event.event_type,
                    description=event.description,
                    timestamp=event.timestamp,
                    source="backend",
                )
            )
    dated = sorted(
        (event for event in events if event.timestamp is not None),
        key=lambda event: event.timestamp,
    )
    undated = [event for event in events if event.timestamp is None]
    return dated + undated


def _neutral_summary(analysis: SupportCaseAnalysisResult, item_count: int) -> str:
    outcome = (
        analysis.recommendation.outcome.value
        if analysis.recommendation
        else "no recommendation"
    )
    requested = analysis.requested_resolution or "no specific resolution"
    return (
        f"Case {analysis.case_id}: the customer reported issue type "
        f"{analysis.issue_type.value} and requested {requested}. "
        f"{item_count} evidence item(s) were analyzed; "
        f"{len(analysis.contradictions)} contradiction(s) and "
        f"{len(analysis.missing_information)} missing-information item(s) "
        f"were identified. Recommended outcome: {outcome}. A human support "
        "agent must make the final decision."
    )


def _fallback_report(
    analysis: SupportCaseAnalysisResult,
    ticket: SupportTicket,
    evidence_items: Sequence[EvidenceItem],
    order_information: OrderInformation | None,
    payment_information: PaymentInformation | None,
    case_context: CaseContext | None,
    error_name: str,
) -> InvestigationReport:
    """Deterministic fallback preserving the underlying structured findings."""
    items = [item for item in evidence_items if isinstance(item, EvidenceItem)]
    recommendation = analysis.recommendation
    limitations = list(analysis.limitations) + [
        f"Report generation failed ({error_name}); a deterministic fallback "
        "report was produced. The underlying structured findings are "
        "preserved in the analysis result."
    ]
    created_at = case_context.created_at if case_context else None
    return InvestigationReport(
        case_id=analysis.case_id,
        case_overview=SupportCaseOverview(
            case_id=analysis.case_id,
            issue_type=analysis.issue_type,
            product_name=ticket.product_name,
            requested_resolution=analysis.requested_resolution,
            complaint_summary=analysis.customer_claim_summary,
            created_at=created_at,
        ),
        customer_complaint=ticket.complaint,
        requested_resolution=analysis.requested_resolution,
        customer_claims=_claim_copies(analysis),
        purchase_and_order_information=analysis.purchase_information,
        order_information=order_information,
        payment_information=payment_information,
        evidence_inventory=[_inventory_entry(item) for item in items],
        visual_analysis=analysis.visual_analysis,
        conversation_analysis=analysis.conversation_analysis,
        cross_source_verification=analysis.cross_source_findings,
        supporting_findings=analysis.claims,
        contradictions=analysis.contradictions,
        missing_information=analysis.missing_information,
        policy_assessment=analysis.policy_evaluation,
        recommended_outcome=(
            recommendation.outcome
            if recommendation
            else RecommendationOutcome.INSUFFICIENT_POLICY_INFORMATION
        ),
        recommendation_reasoning=recommendation.reasoning if recommendation else "",
        recommendation=recommendation,
        evidence_references=[
            f"{item.evidence_id} — {item.filename}" for item in items
        ],
        neutral_summary=(
            f"Case {analysis.case_id}: fallback report (generation error "
            f"{error_name}). See the structured analysis result for the "
            "complete findings."
        ),
        limitations=limitations,
        human_review_required=True,
        unresolved_evidence_ids=[
            item.evidence_id
            for item in items
            if item.status.value in {"needs_review", "failed"}
        ],
        source_summary=analysis.source_summary,
        generation_method="heuristic",
    )
