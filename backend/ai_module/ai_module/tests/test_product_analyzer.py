"""Tests for purchase/receipt fact extraction."""

from datetime import datetime

import pytest

from _fakes import FakeLLMProvider
from proofbridge_ai.exceptions import InputValidationError, ProviderError
from proofbridge_ai.schemas import EvidenceItem, EvidenceKind
from proofbridge_ai.services import product_analyzer
from proofbridge_ai.services.product_analyzer import _PurchaseFacts

RECEIPT_TEXT = (
    "SoundWave Electronics\n"
    "Receipt\n"
    "Order #ORD-2026-1101\n"
    "1x AeroBuds Pro Wireless Headphones  $89.99 USD\n"
    "Date: November 1, 2026\n"
    "Qty: 1\n"
)


def make_item(text=RECEIPT_TEXT, evidence_id="RCPT-1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        filename="receipt.txt",
        kind=EvidenceKind.TEXT,
        extracted_text=text,
    )


def test_heuristic_extraction_uses_only_verifiable_values():
    info = product_analyzer.extract_purchase_information(make_item())
    assert info.evidence_id == "RCPT-1"
    assert info.order_number == "ORD-2026-1101"
    assert info.purchase_date == datetime(2026, 11, 1)
    assert info.price == 89.99
    assert info.currency == "USD"
    assert info.quantity == 1
    # Names the heuristic cannot verify are left None, never invented:
    assert info.seller_name is None
    assert info.product_name is None


def test_llm_verified_values_kept_and_unverifiable_dropped():
    fake = FakeLLMProvider(
        _PurchaseFacts(
            seller_name="SoundWave Electronics",
            product_name="AeroBuds Pro Wireless Headphones",
            product_model="AeroBuds Pro",
            order_number="ORD-2026-1101",
            purchase_date=datetime(2026, 11, 1),
            price=89.99,
            currency="USD",
            quantity=1,
        )
    )
    info = product_analyzer.extract_purchase_information(make_item(), llm=fake)
    assert info.seller_name == "SoundWave Electronics"
    assert info.product_name == "AeroBuds Pro Wireless Headphones"
    assert info.order_number == "ORD-2026-1101"
    assert info.purchase_date == datetime(2026, 11, 1)
    assert info.price == 89.99
    assert info.currency == "USD"
    assert info.quantity == 1


def test_llm_values_not_present_in_text_are_dropped_with_warning():
    fake = FakeLLMProvider(
        _PurchaseFacts(
            seller_name="Totally Fake Shop",
            order_number="ORD-0000-XXXX",
            purchase_date=datetime(1999, 1, 1),
            price=1234.56,
            currency="USD",
            quantity=7,
        )
    )
    info = product_analyzer.extract_purchase_information(make_item(), llm=fake)
    assert info.seller_name is None
    assert info.order_number is None
    assert info.purchase_date is None
    assert info.price is None
    assert info.quantity is None
    assert len(info.extraction_warnings) >= 4
    assert all(w.code == "llm_value_dropped" for w in info.extraction_warnings)


def test_llm_failure_falls_back_to_heuristics():
    fake = FakeLLMProvider(error=ProviderError("boom", provider="fake"))
    info = product_analyzer.extract_purchase_information(make_item(), llm=fake)
    assert info.order_number == "ORD-2026-1101"
    assert any(w.code == "purchase_llm_fallback" for w in info.extraction_warnings)


def test_empty_text_warns_and_returns_nothing():
    info = product_analyzer.extract_purchase_information(make_item(text=""))
    assert info.seller_name is None
    assert info.price is None
    assert any(w.code == "no_text_extracted" for w in info.extraction_warnings)


def test_euro_and_date_variants_parse():
    text = "Order 2026-11-05\nTotal: €49.95 EUR\n"
    info = product_analyzer.extract_purchase_information(make_item(text=text))
    assert info.purchase_date == datetime(2026, 11, 5)
    assert info.price == 49.95
    assert info.currency == "EUR"


def test_invalid_input_raises():
    with pytest.raises(InputValidationError):
        product_analyzer.extract_purchase_information("nope")  # type: ignore[arg-type]
