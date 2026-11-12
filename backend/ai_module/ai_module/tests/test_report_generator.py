"""Tests for structured investigation report generation."""

from datetime import datetime, timedelta, timezone

import pytest

from proofbridge_ai.exceptions import InputValidationError
from proofbridge_ai.schemas import (
    FINAL_DECISION_NOTICE,
    REPORT_SCHEMA_VERSION,
    REPORT_TITLE,
    AnalysisSource,
    CaseContext,
    CaseEvent,
    ClaimAssessment,
    Contradiction,
    EvidenceInventoryStatus,
    EvidenceItem,
    EvidenceKind,
    ExtractionWarning,
    FieldValueObservation,
    IssueType,
    MissingInformation,
    OrderInformation,
    PolicyEvaluationResult,
    PolicyEvaluationStatus,
    PolicyRuleAssessment,
    PolicyRuleCategory,
    RecommendationOutcome,
    RefundRecommendation,
    RuleAssessment,
    SourceSummary,
    SupportCaseAnalysisResult,
    SupportTicket,
    VerificationStatus,
)
from proofbridge_ai.services import report_generator
from proofbridge_ai.services.report_generator import (
    generate_investigation_report,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _ticket() -> SupportTicket:
    return SupportTicket(
        case_id="case-1",
        complaint="My SonicWave Pro arrived with a cracked left ear cup.",
        product_name="SonicWave Pro Wireless Headphones",
        requested_resolution="refund",
        purchase_date=datetime(2026, 10, 1, 12, 0),
        delivery_date=datetime(2026, 10, 5, 12, 0),
    )


def _analysis() -> SupportCaseAnalysisResult:
    return SupportCaseAnalysisResult(
        case_id="case-1",
        issue_type=IssueType.DAMAGED_PRODUCT,
        requested_resolution="refund",
        customer_claim_summary="The customer reports a cracked left ear cup.",
        claims=[
            ClaimAssessment(
                claim_id="claim-1",
                claim="My SonicWave Pro arrived with a cracked left ear cup.",
                source="customer_ticket",
                status=VerificationStatus.PARTIALLY_SUPPORTED,
                confidence=0.8,
                rationale="A product photo shows a crack; cause and timing "
                "cannot be established from a photograph.",
                supporting_evidence_ids=["evt-photo"],
                analysis_method="heuristic",
                source_kind=AnalysisSource.HEURISTIC,
            )
        ],
        purchase_information=[],
        visual_analysis=[],
        conversation_analysis=[],
        cross_source_findings=[],
        contradictions=[
            Contradiction(
                id="contra-1",
                field="order_id",
                description="The order number differs across sources: "
                "customer_ticket states 'ORD-111', receipt states 'ORD-222'. "
                "This does not imply wrongdoing by either party.",
                evidence_ids=["evt-receipt"],
                observed_values=[
                    FieldValueObservation(
                        value="ORD-111", source="customer_ticket"
                    ),
                    FieldValueObservation(
                        value="ORD-222", source="receipt", evidence_id="evt-receipt"
                    ),
                ],
            )
        ],
        missing_information=[
            MissingInformation(
                id="missing-1",
                description="The receipt does not state a purchase date.",
                recommended_evidence=["receipt with purchase date"],
            )
        ],
        policy_evaluation=PolicyEvaluationResult(
            policy_id="pol-1",
            policy_name="Store Refund Policy",
            status=PolicyEvaluationStatus.EVALUATED,
            rule_assessments=[
                PolicyRuleAssessment(
                    rule_id="rule-1",
                    condition="Items may be returned within 30 days of purchase.",
                    category=PolicyRuleCategory.RETURN_WINDOW,
                    assessment=RuleAssessment.MET,
                    evidence_ids=["evt-receipt"],
                    explanation="The purchase date is within the return window.",
                    source_quote="Items may be returned within 30 days of purchase.",
                )
            ],
            explanation="Policy evaluated.",
        ),
        recommendation=RefundRecommendation(
            outcome=RecommendationOutcome.REQUEST_MORE_INFORMATION,
            reasoning="A product photo supports the damage report, but cause "
            "and timing cannot be established.",
            supporting_evidence_ids=["evt-photo"],
            relevant_policy_rule_ids=["rule-1"],
            confidence=0.6,
        ),
        limitations=["A photograph cannot establish when damage occurred."],
        source_summary=SourceSummary(llm_count=2, heuristic_count=5),
    )


def _item(
    evidence_id: str,
    *,
    status: EvidenceInventoryStatus = EvidenceInventoryStatus.PROCESSED,
    ocr_applied: bool = False,
    extracted_text: str = "",
    uploaded_at: datetime | None = None,
    warning_codes: list[str] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        filename=f"{evidence_id}.png",
        kind=EvidenceKind.IMAGE,
        status=status,
        extracted_text=extracted_text,
        ocr_applied=ocr_applied,
        uploaded_at=uploaded_at,
        extraction_warnings=[
            ExtractionWarning(code=code, message=f"warning {code}")
            for code in (warning_codes or [])
        ],
    )


def test_report_has_mandatory_title_schema_and_notices():
    report = generate_investigation_report(_analysis(), _ticket())

    assert report.report_title == REPORT_TITLE
    assert report.schema_version == REPORT_SCHEMA_VERSION
    assert REPORT_SCHEMA_VERSION == "2.0"
    assert report.final_decision_notice == FINAL_DECISION_NOTICE
    assert report.human_review_required is True
    assert report.generation_method == "heuristic"


def test_report_copies_findings_verbatim():
    analysis = _analysis()
    report = generate_investigation_report(analysis, _ticket())

    assert report.contradictions == analysis.contradictions
    assert report.missing_information == analysis.missing_information
    assert report.policy_assessment == analysis.policy_evaluation
    assert report.recommendation == analysis.recommendation
    assert report.supporting_findings == analysis.claims
    assert report.limitations == analysis.limitations
    assert report.recommended_outcome == RecommendationOutcome.REQUEST_MORE_INFORMATION
    assert report.recommendation_reasoning == analysis.recommendation.reasoning
    assert report.case_overview.issue_type == IssueType.DAMAGED_PRODUCT
    assert report.customer_complaint.startswith("My SonicWave Pro")


def test_report_customer_claims_are_display_copies():
    analysis = _analysis()
    report = generate_investigation_report(analysis, _ticket())

    claim = report.customer_claims[0]
    assessment = analysis.claims[0]
    assert claim.id == assessment.claim_id
    assert claim.claim == assessment.claim
    assert claim.verification_status == VerificationStatus.PARTIALLY_SUPPORTED
    assert claim.supporting_evidence_ids == ["evt-photo"]
    assert claim.rationale == assessment.rationale


def test_evidence_inventory_entries_and_warning_codes():
    item = _item("evt-1", warning_codes=["ocr_warning", "low_quality"])
    report = generate_investigation_report(_analysis(), _ticket(), [item])

    entry = report.evidence_inventory[0]
    assert entry.evidence_id == "evt-1"
    assert entry.filename == "evt-1.png"
    assert entry.kind is EvidenceKind.IMAGE
    assert entry.status is EvidenceInventoryStatus.PROCESSED
    assert entry.extraction_warning_codes == ["ocr_warning", "low_quality"]
    assert report.evidence_references == ["evt-1 — evt-1.png"]


def test_ocr_findings_only_for_items_with_ocr_applied():
    ocr_item = _item(
        "evt-ocr",
        ocr_applied=True,
        extracted_text="Receipt text " * 80,
        warning_codes=["x"],
    )
    plain_item = _item("evt-plain", extracted_text="hidden from ocr findings")
    report = generate_investigation_report(_analysis(), _ticket(), [ocr_item, plain_item])

    assert [f.evidence_id for f in report.ocr_findings] == ["evt-ocr"]
    finding = report.ocr_findings[0]
    assert len(finding.text_excerpt) <= 303
    assert "Receipt text" in finding.text_excerpt
    assert finding.warnings == ["x"]


def test_policy_summary_present_and_none_without_policy():
    report = generate_investigation_report(_analysis(), _ticket())
    summary = report.refund_policy_summary
    assert summary is not None
    assert summary.policy_id == "pol-1"
    assert summary.policy_name == "Store Refund Policy"
    assert summary.rule_count == 1
    assert summary.rule_summaries == ["Items may be returned within 30 days of purchase."]

    analysis = _analysis()
    analysis.policy_evaluation = None
    report = generate_investigation_report(analysis, _ticket())
    assert report.refund_policy_summary is None


def test_timeline_dated_sorted_undated_last_no_invented_timestamps():
    ticket = _ticket()
    early = _item("evt-early", uploaded_at=datetime(2026, 10, 2, 9, 0))
    late = _item("evt-late", uploaded_at=datetime(2026, 10, 6, 9, 0))
    undated = _item("evt-undated")
    context = CaseContext(
        case_id="case-1",
        title="Damaged headphones",
        events=[
            CaseEvent(
                event_type="agent_note",
                description="Agent reviewed the photo.",
                timestamp=datetime(2026, 10, 8, 14, 0),
            ),
            CaseEvent(
                event_type="agent_note_undated",
                description="No timestamp supplied.",
                timestamp=None,
            ),
        ],
    )
    report = generate_investigation_report(
        _analysis(), ticket, [undated, late, early], case_context=context
    )

    timestamps = [event.timestamp for event in report.timeline]
    dated = [t for t in timestamps if t is not None]
    assert dated == sorted(dated)
    assert timestamps[-1] is None
    sources = {event.source for event in report.timeline}
    assert "customer_ticket" in sources
    assert "evidence:evt-early" in sources
    assert "backend" in sources
    described = {event.description for event in report.timeline}
    assert "No timestamp supplied." in described


def test_neutral_summary_is_deterministic_and_mentions_outcome():
    first = generate_investigation_report(_analysis(), _ticket())
    second = generate_investigation_report(_analysis(), _ticket())

    assert first.neutral_summary == second.neutral_summary
    assert "request_more_information" in first.neutral_summary
    assert "human support" in first.neutral_summary
    assert first.generation_method == "heuristic"


def test_unresolved_evidence_ids_and_status_counts():
    needs_review = _item("evt-review", status=EvidenceInventoryStatus.NEEDS_REVIEW)
    failed = _item("evt-failed", status=EvidenceInventoryStatus.FAILED)
    processed = _item("evt-ok")
    report = generate_investigation_report(
        _analysis(), _ticket(), [needs_review, failed, processed]
    )

    assert sorted(report.unresolved_evidence_ids) == ["evt-failed", "evt-review"]
    assert report.status_counts == {
        VerificationStatus.PARTIALLY_SUPPORTED: 1,
    }


def test_product_information_uses_order_model_when_available():
    report = generate_investigation_report(
        _analysis(),
        _ticket(),
        order_information=OrderInformation(
            order_id="ORD-222", product_model="SW-PRO-2026"
        ),
    )
    assert report.product_information == (
        "Product: SonicWave Pro Wireless Headphones (model SW-PRO-2026)"
    )


def test_order_and_payment_information_verbatim():
    order = OrderInformation(order_id="ORD-222", product_model="SW-PRO-2026")
    report = generate_investigation_report(_analysis(), _ticket(), order_information=order)
    assert report.order_information == order


def test_fallback_report_preserves_findings(monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("synthetic report failure")

    monkeypatch.setattr(report_generator, "_build_report", boom)

    analysis = _analysis()
    report = generate_investigation_report(_analysis(), _ticket())

    assert report.contradictions == analysis.contradictions
    assert report.missing_information == analysis.missing_information
    assert report.supporting_findings == analysis.claims
    assert report.human_review_required is True
    assert any(
        "fallback" in limitation and "ValueError" in limitation
        for limitation in report.limitations
    )
    assert "fallback" in report.neutral_summary


def test_invalid_inputs_raise_input_validation_error():
    with pytest.raises(InputValidationError):
        generate_investigation_report(None, _ticket())
    with pytest.raises(InputValidationError):
        generate_investigation_report(_analysis(), None)


def test_report_from_real_pipeline_is_consistent():
    from proofbridge_ai.services.support_case_analyzer import (
        analyze_support_case,
    )
    import asyncio

    ticket = SupportTicket(
        case_id="case-9",
        complaint="My order ORD-777 arrived damaged; the left ear cup is "
        "cracked. I contacted the seller and want a refund.",
        requested_resolution="refund",
        purchase_date=datetime(2026, 10, 1, 12, 0),
    )
    receipt_text = (
        "Receipt\nOrder #ORD-777\nDate: October 1, 2026\n"
        "SonicWave Pro Wireless Headphones\nTotal: $49.99\nQuantity: 1"
    )
    evidence = [
        {
            "evidence_id": "evt-receipt",
            "filename": "receipt.txt",
            "kind": "text",
            "category": "purchase_record",
            "content_type": "text/plain",
            "file_bytes": receipt_text.encode("utf-8"),
        },
    ]
    from proofbridge_ai.config import Settings

    settings = Settings(demo_mode=True)
    result = asyncio.run(
        analyze_support_case(
            ticket,
            evidence,
            settings=settings,
        )
    )
    report = generate_investigation_report(result, ticket, [])
    assert report.case_id == "case-9"
    assert report.schema_version == "2.0"
    assert report.report_title == REPORT_TITLE
    assert report.recommended_outcome is result.recommendation.outcome
    assert report.human_review_required is True
