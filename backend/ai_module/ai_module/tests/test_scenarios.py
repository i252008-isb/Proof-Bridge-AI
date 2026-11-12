"""Scenario tests A-J from the master prompt (offline, deterministic).

Each scenario exercises the complete pipeline (``analyze_support_case``)
and, where meaningful, the report generator. No paid APIs and no network.
Vision observations come from a scripted fake provider so scenario A can
reach a genuine recommendation without real vision credentials.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image

from proofbridge_ai.config import Settings
from proofbridge_ai.exceptions import ProviderError
from proofbridge_ai.schemas import (
    EvidenceCategory,
    EvidenceInput,
    EvidenceUpload,
    RecommendationOutcome,
    SupportTicket,
    VerificationStatus,
    VisionStatus,
    VisualAnalysisResult,
    VisualObservation,
)
from proofbridge_ai.services import support_case_analyzer
from proofbridge_ai.services.policy_extractor import extract_refund_policy
from proofbridge_ai.services.report_generator import (
    generate_investigation_report,
)

NOW = datetime.now(timezone.utc)

POLICY_A = (
    "Items may be returned within 30 days of purchase. "
    "Items that arrive damaged may be replaced or refunded when "
    "photographic proof of the damage is provided."
)


def _settings():
    return Settings(
        demo_mode=True,
        similarity_partial_threshold=0.0,
        similarity_supported_threshold=0.0,
    )


def _ticket(complaint, order_id="ORD-1001", purchase_date=None, requested="refund"):
    return SupportTicket(
        case_id="SCN",
        complaint=complaint,
        order_id=order_id,
        purchase_date=purchase_date,
        requested_resolution=requested,
    )


def _upload(evidence_id, filename, content, category=None, content_type=None):
    return EvidenceUpload(
        file_bytes=content.encode() if isinstance(content, str) else content,
        evidence_input=EvidenceInput(
            evidence_id=evidence_id, filename=filename, category=category
        ),
        content_type=content_type,
    )


def _receipt(order_number="ORD-1001", purchase_date="October 1, 2026"):
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


def _photo():
    buffer = BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, format="PNG")
    return _upload(
        "evt-photo",
        "photo.png",
        buffer.getvalue(),
        category=EvidenceCategory.PRODUCT_IMAGE,
        content_type="image/png",
    )


def _policy(text):
    return extract_refund_policy(policy_text=text, policy_id="pol-1", policy_name="Store Policy")


def _run(coro):
    return asyncio.run(coro)


def _fake_vision(file_bytes, evidence_input, content_type=None, **kwargs):
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


def _recent_purchase(days_ago=5):
    purchase = NOW - timedelta(days=days_ago)
    return purchase, f"{purchase.strftime('%B')} {purchase.day}, {purchase.year}"


# ---------------------------------------------------------------- scenario A


def test_scenario_A_damaged_product_receipt_and_photo(monkeypatch):
    """Damaged product + matching receipt + photo -> REFUND_RECOMMENDED."""
    monkeypatch.setattr(
        support_case_analyzer, "analyze_visual_evidence", _fake_vision
    )
    purchase, receipt_date = _recent_purchase(5)
    ticket = _ticket(
        "My order ORD-1001 arrived damaged; the left ear cup is cracked. "
        "I want a refund.",
        purchase_date=purchase,
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_receipt(purchase_date=receipt_date), _photo()],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    assert result.recommendation is not None
    assert result.recommendation.outcome is RecommendationOutcome.REFUND_RECOMMENDED
    statuses = {a.claim_id: a.status for a in result.claims}
    assert any(status is VerificationStatus.SUPPORTED for status in statuses.values())
    report = generate_investigation_report(result, ticket)
    assert report.recommended_outcome is RecommendationOutcome.REFUND_RECOMMENDED
    assert report.visual_analysis
    assert report.human_review_required is True


# ---------------------------------------------------------------- scenario B


def test_scenario_B_missing_receipt(monkeypatch):
    """No receipt -> the pipeline asks for more information, never guesses."""
    monkeypatch.setattr(
        support_case_analyzer, "analyze_visual_evidence", _fake_vision
    )
    ticket = _ticket(
        "My headphones arrived damaged; the left ear cup is cracked.",
        order_id=None,
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_photo()],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    assert result.recommendation is not None
    assert result.recommendation.outcome is RecommendationOutcome.REQUEST_MORE_INFORMATION
    assert result.missing_information


# ---------------------------------------------------------------- scenario C


def test_scenario_C_inconsistent_order_details():
    """Receipt order number differs from the ticket -> escalation."""
    ticket = _ticket(
        "My order ORD-111 arrived damaged with a cracked ear cup.",
        order_id="ORD-111",
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_receipt(order_number="ORD-222")],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    assert result.contradictions
    assert result.recommendation is not None
    assert result.recommendation.outcome is RecommendationOutcome.ESCALATE_TO_HUMAN
    assert any(
        a.status is VerificationStatus.CONTRADICTED for a in result.claims
    )


# ---------------------------------------------------------------- scenario D


def test_scenario_D_policy_not_supplied():
    """No policy -> insufficient_policy_information, never invented policy."""
    ticket = _ticket("My headphones arrived damaged with a cracked ear cup.")
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket, [_receipt()], settings=_settings()
        )
    )

    assert result.recommendation is not None
    assert result.recommendation.outcome is (
        RecommendationOutcome.INSUFFICIENT_POLICY_INFORMATION
    )
    assert result.policy_evaluation is not None
    assert result.policy_evaluation.status.value == "policy_not_provided"


# ---------------------------------------------------------------- scenario E


def test_scenario_E_customer_seller_conversation(monkeypatch):
    """Seller chat is analyzed as a separate evidence source."""
    monkeypatch.setattr(
        support_case_analyzer, "analyze_visual_evidence", _fake_vision
    )
    chat = _upload(
        "evt-chat",
        "chat.txt",
        (
            "customer: The left ear cup arrived cracked.\n"
            "seller: Sorry to hear that. Please send a photo.\n"
            "customer: Photo attached.\n"
            "seller: Thank you, we will check and get back to you."
        ),
        category=EvidenceCategory.CONVERSATION,
    )
    purchase, receipt_date = _recent_purchase(5)
    ticket = _ticket(
        "My order ORD-1001 arrived damaged; the seller asked for a photo. "
        "I want a refund.",
        purchase_date=purchase,
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_receipt(purchase_date=receipt_date), _photo(), chat],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    assert result.conversation_analysis
    conversation = result.conversation_analysis[0]
    assert any(m.speaker.value == "customer" for m in conversation.messages)
    assert any(m.speaker.value == "seller" for m in conversation.messages)
    report = generate_investigation_report(result, ticket)
    assert report.conversation_analysis == result.conversation_analysis


# ---------------------------------------------------------------- scenario F


def test_scenario_F_late_complaint_vs_policy_window():
    """Purchase far outside the return window -> not supported by policy,
    explicitly not a definitive rejection."""
    ticket = _ticket(
        "My headphones arrived damaged and I want a refund.",
        order_id=None,
        purchase_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_receipt(purchase_date="January 1, 2026")],
            refund_policy=_policy("Items may be returned within 30 days of purchase."),
            settings=_settings(),
        )
    )

    assert result.recommendation is not None
    assert (
        result.recommendation.outcome
        is RecommendationOutcome.REFUND_NOT_SUPPORTED_BY_PROVIDED_POLICY
    )
    assert "not a definitive rejection" in result.recommendation.reasoning.lower()


# ---------------------------------------------------------------- scenario G


def test_scenario_G_vision_unavailable(monkeypatch):
    """Vision provider failure degrades gracefully; the case continues."""

    def broken_vision(*args, **kwargs):
        raise ProviderError("vision service unreachable", provider="vision")

    monkeypatch.setattr(
        support_case_analyzer, "analyze_visual_evidence", broken_vision
    )
    purchase, receipt_date = _recent_purchase(5)
    ticket = _ticket(
        "My order ORD-1001 arrived damaged; the left ear cup is cracked.",
        purchase_date=purchase,
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_receipt(purchase_date=receipt_date), _photo()],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    assert any(
        "evt-photo" in limitation and "ProviderError" in limitation
        for limitation in result.limitations
    )
    assert any(
        "continued" in limitation for limitation in result.limitations
    )
    report = generate_investigation_report(result, ticket)
    assert report.limitations == result.limitations


# ---------------------------------------------------------------- scenario H


def test_scenario_H_unreadable_image():
    """One unreadable upload is isolated; other evidence still processes."""
    unreadable = _upload(
        "evt-broken",
        "broken.png",
        b"this is not an image",
        category=EvidenceCategory.PRODUCT_IMAGE,
        content_type="image/png",
    )
    ticket = _ticket("My headphones arrived damaged with a cracked ear cup.")
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [unreadable, _receipt()],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    assert any("evt-broken" in limitation for limitation in result.limitations)
    assert any(
        purchase.evidence_id == "evt-receipt"
        for purchase in result.purchase_information
    )


# ---------------------------------------------------------------- scenario I


def test_scenario_I_conflicting_dates():
    """Ticket date vs receipt date conflict -> factual contradiction."""
    ticket = _ticket(
        "My headphones arrived damaged. I bought them on October 1, 2026.",
        purchase_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [_receipt(purchase_date="September 25, 2026")],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    date_contradictions = [
        c for c in result.contradictions if c.field == "purchase_date"
    ]
    assert date_contradictions
    description = date_contradictions[0].description.lower()
    assert "wrongdoing" in description


# ---------------------------------------------------------------- scenario J


def test_scenario_J_unrelated_evidence():
    """Unrelated evidence neither supports nor contradicts the claims."""
    unrelated = _upload(
        "evt-garden",
        "gardening.txt",
        (
            "Gardening tips: water tomatoes twice a week, prune roses in "
            "spring, and use mulch to retain moisture."
        ),
        category=EvidenceCategory.OTHER,
    )
    ticket = _ticket("My headphones arrived damaged with a cracked ear cup.")
    result = _run(
        support_case_analyzer.analyze_support_case(
            ticket,
            [unrelated],
            refund_policy=_policy(POLICY_A),
            settings=_settings(),
        )
    )

    assert all(
        assessment.status is not VerificationStatus.SUPPORTED
        for assessment in result.claims
    )
    assert all(
        assessment.status in {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.INSUFFICIENT_EVIDENCE,
        }
        for assessment in result.claims
    )
    report = generate_investigation_report(result, ticket)
    assert report.schema_version == "2.0"
    assert report.human_review_required is True
