"""Tests for services.cross_source_verifier: factual consistency checks."""

from datetime import datetime

import pytest

from proofbridge_ai.exceptions import InputValidationError
from proofbridge_ai.schemas import (
    ConversationAnalysis,
    OrderInformation,
    PaymentInformation,
    PurchaseInformation,
    SupportTicket,
    VerificationStatus,
)
from proofbridge_ai.services.cross_source_verifier import verify_cross_source


def _ticket(order_id="ORD-1001", product_name=None, purchase_date=None):
    return SupportTicket(
        case_id="C-1",
        complaint="My product arrived damaged.",
        order_id=order_id,
        product_name=product_name,
        purchase_date=purchase_date,
    )


def _purchase(order_number="ORD-1001", price=None, purchase_date=None):
    return PurchaseInformation(
        evidence_id="evt-receipt", order_number=order_number, price=price,
        purchase_date=purchase_date,
    )


def test_agreement_produces_supported_finding():
    findings, contradictions, missing = verify_cross_source(
        _ticket(order_id="ORD-1001"), purchase_information=_purchase("ORD-1001")
    )
    assert contradictions == []
    order_findings = [f for f in findings if f.field == "order_id"]
    assert len(order_findings) == 1
    assert order_findings[0].status is VerificationStatus.SUPPORTED
    assert "ORD-1001" in order_findings[0].rationale


def test_order_id_mismatch_is_factual_contradiction():
    findings, contradictions, _ = verify_cross_source(
        _ticket(order_id="ORD-1001"), purchase_information=_purchase("ORD-9999")
    )
    assert len(contradictions) == 1
    contradiction = contradictions[0]
    assert contradiction.field == "order_id"
    assert "ORD-1001" in contradiction.description
    assert "ORD-9999" in contradiction.description
    assert "dishonest" not in contradiction.description
    assert "fraud" not in contradiction.description
    finding = [f for f in findings if f.field == "order_id"][0]
    assert finding.status is VerificationStatus.CONTRADICTED
    assert finding.contradicting_evidence_ids == ["evt-receipt"]


def test_similar_product_names_are_partially_supported():
    findings, contradictions, _ = verify_cross_source(
        _ticket(product_name="SonicWave Pro Wireless Headphones"),
        purchase_information=PurchaseInformation(
            evidence_id="evt-receipt",
            product_name="Wireless Headphones SonicWave Pro",
        ),
    )
    assert contradictions == []
    finding = [f for f in findings if f.field == "product_name"][0]
    assert finding.status is VerificationStatus.PARTIALLY_SUPPORTED


def test_clearly_different_product_names_are_contradicted():
    findings, contradictions, _ = verify_cross_source(
        _ticket(product_name="Wireless Headphones"),
        purchase_information=PurchaseInformation(
            evidence_id="evt-receipt", product_name="Mechanical Keyboard"
        ),
    )
    assert any(c.field == "product_name" for c in contradictions)
    finding = [f for f in findings if f.field == "product_name"][0]
    assert finding.status is VerificationStatus.CONTRADICTED


def test_single_source_produces_no_finding():
    findings, contradictions, missing = verify_cross_source(_ticket())
    assert findings == []
    assert contradictions == []


def test_missing_independent_source_is_reported():
    _, _, missing = verify_cross_source(_ticket(order_id="ORD-1001"))
    assert any(
        "could not be independently confirmed" in item.description
        for item in missing
    )


def test_receipt_without_order_number_is_reported():
    _, _, missing = verify_cross_source(
        _ticket(order_id="ORD-1001"),
        purchase_information=PurchaseInformation(evidence_id="evt-receipt"),
    )
    assert any(
        "does not state an order number" in item.description for item in missing
    )


def test_conflicting_purchase_dates():
    findings, contradictions, _ = verify_cross_source(
        _ticket(purchase_date=datetime(2026, 10, 1)),
        purchase_information=_purchase(purchase_date=datetime(2026, 9, 15)),
    )
    assert any(c.field == "purchase_date" for c in contradictions)
    finding = [f for f in findings if f.field == "purchase_date"][0]
    assert finding.status is VerificationStatus.CONTRADICTED


def test_price_contradiction_with_payment_provider():
    findings, contradictions, _ = verify_cross_source(
        _ticket(order_id="ORD-1001"),
        purchase_information=_purchase("ORD-1001", price=49.99),
        order_information=OrderInformation(order_id="ORD-1001", price=49.99),
        payment_information=PaymentInformation(
            transaction_id="TXN-1", order_id="ORD-1001", amount=59.99, currency="USD"
        ),
    )
    assert any(c.field == "price" for c in contradictions)
    price_finding = [f for f in findings if f.field == "price"][0]
    assert price_finding.status is VerificationStatus.CONTRADICTED


def test_currency_comparison_is_case_insensitive():
    findings, contradictions, _ = verify_cross_source(
        _ticket(order_id="ORD-1001"),
        purchase_information=PurchaseInformation(
            evidence_id="evt-receipt", order_number="ORD-1001", currency="usd"
        ),
        payment_information=PaymentInformation(
            transaction_id="TXN-1", order_id="ORD-1001", amount=49.99, currency="USD"
        ),
    )
    assert not any(c.field == "currency" for c in contradictions)
    currency_finding = [f for f in findings if f.field == "currency"][0]
    assert currency_finding.status is VerificationStatus.SUPPORTED


def test_chat_contradictions_are_reported_factually():
    chat = ConversationAnalysis(
        evidence_id="evt-chat",
        contradictions=[
            "The seller first promised a refund and later stated that "
            "refunds are not offered; both statements appear in the chat."
        ],
    )
    _, contradictions, _ = verify_cross_source(_ticket(), conversation_analysis=chat)
    assert any(c.field == "conversation" for c in contradictions)
    chat_contradiction = [c for c in contradictions if c.field == "conversation"][0]
    assert chat_contradiction.evidence_ids == ["evt-chat"]


def test_invalid_ticket_raises():
    with pytest.raises(InputValidationError):
        verify_cross_source("not-a-ticket")
