"""Tests for services.support_case_analyzer: the main investigation pipeline."""

import asyncio
from datetime import datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image

from proofbridge_ai.config import Settings
from proofbridge_ai.exceptions import InputValidationError
from proofbridge_ai.schemas import (
    CustomerClaim,
    EvidenceCategory,
    EvidenceInput,
    EvidenceItem,
    EvidenceKind,
    EvidenceUpload,
    PolicyEvaluationStatus,
    RecommendationOutcome,
    RefundPolicy,
    SupportTicket,
    VerificationStatus,
    VisionStatus,
    VisualAnalysisResult,
    VisualObservation,
)
from proofbridge_ai.services import support_case_analyzer


def _settings(partial_threshold=0.0, supported_threshold=0.0):
    return Settings(
        demo_mode=True,
        similarity_partial_threshold=partial_threshold,
        similarity_supported_threshold=supported_threshold,
    )


def _ticket(
    case_id="C-1",
    complaint="My headphones arrived damaged with a cracked ear cup.",
    order_id="ORD-1001",
    purchase_date=None,
    requested_resolution="refund",
    claims=None,
):
    return SupportTicket(
        case_id=case_id,
        complaint=complaint,
        order_id=order_id,
        purchase_date=purchase_date,
        requested_resolution=requested_resolution,
        claims=claims or [],
    )


def _upload(evidence_id, filename, text, category=None, content_type=None):
    return EvidenceUpload(
        file_bytes=text.encode() if isinstance(text, str) else text,
        evidence_input=EvidenceInput(
            evidence_id=evidence_id, filename=filename, category=category
        ),
        content_type=content_type,
    )


def _receipt_upload(order_number="ORD-1001", purchase_date="October 1, 2026"):
    return _upload(
        "evt-receipt",
        "receipt.txt",
        (
            "Receipt\n"
            f"Order #{order_number}\n"
            f"Date: {purchase_date}\n"
            "Total: $49.99\n"
            "Quantity: 1\n"
            "SonicWave Pro Wireless Headphones"
        ),
        category=EvidenceCategory.PURCHASE_RECORD,
    )


def _photo_upload(evidence_id="evt-photo"):
    buffer = BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, format="PNG")
    return EvidenceUpload(
        file_bytes=buffer.getvalue(),
        evidence_input=EvidenceInput(
            evidence_id=evidence_id,
            filename="photo.png",
            category=EvidenceCategory.PRODUCT_IMAGE,
        ),
        content_type="image/png",
    )


def _policy(text):
    from proofbridge_ai.services.policy_extractor import extract_refund_policy

    return extract_refund_policy(
        policy_text=text, policy_id="pol-1", policy_name="Store Policy"
    )


def _run(coro):
    return asyncio.run(coro)


def _fake_vision_with_observations(file_bytes, evidence_input, content_type=None, **kwargs):
    return VisualAnalysisResult(
        evidence_id=evidence_input.evidence_id,
        status=VisionStatus.ANALYZED,
        visual_observations=[
            VisualObservation(
                observation="A visible crack along the left ear cup",
                confidence=0.9,
            )
        ],
        requires_human_review=True,
    )


def test_invalid_inputs_raise():
    with pytest.raises(InputValidationError):
        _run(support_case_analyzer.analyze_support_case("not-a-ticket", []))
    with pytest.raises(InputValidationError):
        _run(support_case_analyzer.analyze_support_case(_ticket(), "not-a-list"))
    with pytest.raises(InputValidationError):
        _run(
            support_case_analyzer.analyze_support_case(
                _ticket(), [], refund_policy="not-a-policy"
            )
        )


def test_full_support_case_recommends_refund(monkeypatch):
    monkeypatch.setattr(
        support_case_analyzer, "analyze_visual_evidence", _fake_vision_with_observations
    )
    purchase = datetime.now() - timedelta(days=5)
    purchase_text = f"{purchase.strftime('%B')} {purchase.day}, {purchase.year}"
    ticket = _ticket(purchase_date=purchase)
    policy = _policy(
        "Items damaged on arrival qualify for a refund. "
        "Customers may return items within 30 days of purchase. "
        "A receipt and a photograph are required."
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_receipt_upload(purchase_date=purchase_text), _photo_upload()],
            refund_policy=policy,
            settings=_settings(),
        )
    )
    assert result.case_id == "C-1"
    assert result.recommendation is not None
    assert result.recommendation.outcome is RecommendationOutcome.REFUND_RECOMMENDED
    assert "evt-receipt" in result.recommendation.supporting_evidence_ids
    assert "evt-photo" in result.recommendation.supporting_evidence_ids
    assert result.recommendation.requires_human_review is True
    assert result.requires_human_review is True
    assert result.policy_evaluation.status is PolicyEvaluationStatus.EVALUATED
    assert result.contradictions == []
    assert result.purchase_information
    assert result.visual_analysis
    assert result.recommendation.relevant_policy_rule_ids


def test_missing_receipt_requests_more_information():
    policy = _policy("A receipt is required for all refunds.")
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(), [], refund_policy=policy, settings=_settings()
        )
    )
    assert result.recommendation.outcome is RecommendationOutcome.REQUEST_MORE_INFORMATION
    assert any("receipt" in item for item in result.recommendation.missing_information)


def test_inconsistent_order_details_escalate_to_human():
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(
                complaint="My order ORD-111 arrived damaged with a cracked ear cup.",
                order_id="ORD-111",
            ),
            [_receipt_upload(order_number="ORD-222")],
            settings=_settings(),
        )
    )
    assert result.contradictions
    assert any(c.field == "order_id" for c in result.contradictions)
    assert result.recommendation.outcome is RecommendationOutcome.ESCALATE_TO_HUMAN
    order_claims = [
        assessment
        for assessment in result.claims
        if "ORD-111" in assessment.claim
    ]
    assert order_claims
    assert all(
        assessment.status is VerificationStatus.CONTRADICTED
        for assessment in order_claims
    )


def test_no_policy_means_insufficient_policy_information():
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(), [_receipt_upload()], settings=_settings()
        )
    )
    assert result.policy_evaluation.status is PolicyEvaluationStatus.POLICY_NOT_PROVIDED
    assert (
        result.recommendation.outcome
        is RecommendationOutcome.INSUFFICIENT_POLICY_INFORMATION
    )
    assert "policy" in result.recommendation.reasoning.lower()


def test_late_complaint_outside_window_not_supported():
    policy = _policy("Customers may return items within 30 days of purchase.")
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(purchase_date=datetime(2026, 1, 1), order_id=None),
            [],
            refund_policy=policy,
            settings=_settings(),
        )
    )
    assert (
        result.recommendation.outcome
        is RecommendationOutcome.REFUND_NOT_SUPPORTED_BY_PROVIDED_POLICY
    )
    assert "not a definitive rejection" in result.recommendation.reasoning.lower()
    assert "final decision" in result.recommendation.reasoning


def test_unreadable_upload_is_isolated(monkeypatch):
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(),
            [
                _upload("evt-broken", "broken.pdf", b"definitely not a pdf"),
                _receipt_upload(),
            ],
            settings=_settings(),
        )
    )
    assert result.purchase_information
    assert any("evt-broken" in limitation for limitation in result.limitations)


def test_backend_supplied_claims_used_verbatim():
    ticket = _ticket(
        claims=[CustomerClaim(id="claim-backend-1", claim="Backend corrected claim.")]
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket, [_receipt_upload()], settings=_settings()
        )
    )
    assert [assessment.claim for assessment in result.claims] == [
        "Backend corrected claim."
    ]


def test_policy_extracted_from_return_policy_evidence():
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(),
            [
                _upload(
                    "evt-policy",
                    "policy.txt",
                    "Customers may return items within 30 days of purchase.",
                    category=EvidenceCategory.RETURN_POLICY,
                ),
                _receipt_upload(),
            ],
            settings=_settings(),
        )
    )
    assert result.policy_evaluation.policy_id == "policy-evt-policy"
    assert result.policy_evaluation.status is PolicyEvaluationStatus.EVALUATED


def test_mixed_processed_and_raw_evidence():
    processed = EvidenceItem(
        evidence_id="evt-chat",
        filename="chat.txt",
        kind=EvidenceKind.TEXT,
        category=EvidenceCategory.CONVERSATION,
        extracted_text="[2026-10-01 10:00] Customer: My item is damaged.\n"
        "[2026-10-01 10:05] Seller: I am sorry to hear that. We will refund you.",
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(),
            [processed, _receipt_upload()],
            settings=_settings(),
        )
    )
    assert len(result.conversation_analysis) == 1
    assert result.conversation_analysis[0].refund_promises


def test_processed_image_without_bytes_is_limited():
    processed = EvidenceItem(
        evidence_id="evt-photo",
        filename="photo.png",
        kind=EvidenceKind.IMAGE,
        category=EvidenceCategory.PRODUCT_IMAGE,
        extracted_text="",
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(), [processed], settings=_settings()
        )
    )
    assert result.visual_analysis == []
    assert any(
        "evt-photo" in limitation and "raw image bytes" in limitation
        for limitation in result.limitations
    )


def test_mock_vision_photo_is_flagged_in_limitations():
    result = _run(
        support_case_analyzer.analyze_support_case(
            _ticket(),
            [_receipt_upload(), _photo_upload()],
            settings=_settings(),
        )
    )
    assert len(result.visual_analysis) == 1
    assert result.visual_analysis[0].status is VisionStatus.MOCK
    assert any("mock vision" in limitation for limitation in result.limitations)


def test_async_alias_returns_same_result():
    ticket = _ticket()
    first = _run(
        support_case_analyzer.arun_support_case_analysis(
            ticket, [_receipt_upload()], settings=_settings()
        )
    )
    second = _run(
        support_case_analyzer.analyze_support_case(
            ticket, [_receipt_upload()], settings=_settings()
        )
    )
    assert first.model_dump(exclude={"generated_at"}) == second.model_dump(
        exclude={"generated_at"}
    )
