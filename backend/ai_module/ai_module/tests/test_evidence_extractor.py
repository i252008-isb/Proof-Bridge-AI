"""Tests for customer-support evidence extraction and classification."""

import pytest

from _ocr_env import tesseract_available
from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import InputValidationError, OCRNotAvailableError
from proofbridge_ai.schemas import (
    EvidenceCategory,
    EvidenceInput,
    EvidenceInventoryStatus,
    EvidenceUpload,
)
from proofbridge_ai.services import evidence_extractor

AVAILABLE = tesseract_available()

RECEIPT_TEXT = (
    "SoundWave Electronics\n"
    "Receipt\n"
    "Order #ORD-2026-1101\n"
    "1x AeroBuds Pro Wireless Headphones  $89.99 USD\n"
    "Date: November 1, 2026\n"
)


def make_input(evidence_id="EV-001", filename="receipt.txt", **overrides) -> EvidenceInput:
    defaults = dict(evidence_id=evidence_id, filename=filename)
    defaults.update(overrides)
    return EvidenceInput(**defaults)


def test_receipt_text_processed_with_inferred_category():
    item = evidence_extractor.extract_evidence(
        RECEIPT_TEXT.encode("utf-8"), make_input(filename="receipt.txt")
    )
    assert item.evidence_id == "EV-001"
    assert item.category is EvidenceCategory.PURCHASE_RECORD
    assert item.status is EvidenceInventoryStatus.PROCESSED
    assert "ORD-2026-1101" in item.extracted_text
    assert any("invoice/reference number" in f for f in item.identified_facts)
    assert any("currency amount" in f for f in item.identified_facts)
    assert any("a date" in f for f in item.identified_facts)


def test_backend_category_label_wins_over_inference():
    item = evidence_extractor.extract_evidence(
        RECEIPT_TEXT.encode("utf-8"),
        make_input(filename="receipt.txt", category=EvidenceCategory.OTHER),
    )
    assert item.category is EvidenceCategory.OTHER


def test_filename_inference_for_chat_policy_delivery():
    cases = [
        ("chat-export.txt", EvidenceCategory.CONVERSATION),
        ("store-return-policy.txt", EvidenceCategory.RETURN_POLICY),
        ("delivery-confirmation.txt", EvidenceCategory.DELIVERY_RECORD),
        ("order-confirmation.txt", EvidenceCategory.ORDER_RECORD),
        ("product-listing.txt", EvidenceCategory.PRODUCT_LISTING),
        ("mystery.txt", EvidenceCategory.OTHER),
    ]
    for filename, expected in cases:
        item = evidence_extractor.extract_evidence(
            b"some text content", make_input(filename=filename)
        )
        assert item.category is expected, filename


def test_metadata_preserved_verbatim():
    item = evidence_extractor.extract_evidence(
        b"content",
        make_input(
            evidence_id="backend-id-42",
            source="customer_upload",
            uploaded_by="customer@example.com",
        ),
    )
    assert item.evidence_id == "backend-id-42"
    assert item.source == "customer_upload"
    assert item.uploaded_by == "customer@example.com"
    assert item.uploaded_at is None  # never invented


def test_empty_text_yields_needs_review(empty_pdf_bytes):
    item = evidence_extractor.extract_evidence(
        empty_pdf_bytes, make_input(filename="empty.pdf")
    )
    assert item.status is EvidenceInventoryStatus.NEEDS_REVIEW
    assert any(w.code == "no_text_extracted" for w in item.extraction_warnings)


def test_batch_isolates_failures():
    good = EvidenceUpload(
        evidence_input=make_input(evidence_id="GOOD-1", filename="note.txt"),
        file_bytes=b"valid text",
    )
    bad = EvidenceUpload(
        evidence_input=make_input(evidence_id="BAD-1", filename="broken.xyz"),
        file_bytes=b"unsupported",
    )
    result = evidence_extractor.extract_evidence_batch([good, bad])
    assert [item.evidence_id for item in result.items] == ["GOOD-1"]
    assert len(result.failures) == 1
    assert result.failures[0].evidence_id == "BAD-1"
    assert result.failures[0].error_type == "UnsupportedFileTypeError"


def test_batch_requires_list_of_uploads():
    with pytest.raises(InputValidationError):
        evidence_extractor.extract_evidence_batch("nope")  # type: ignore[arg-type]


def test_empty_file_bytes_raises():
    with pytest.raises(InputValidationError):
        evidence_extractor.extract_evidence(b"", make_input())


def test_image_without_tesseract_raises_ocr_error():
    from PIL import Image, ImageDraw
    import io

    image = Image.new("RGB", (200, 60), "white")
    ImageDraw.Draw(image).text((10, 20), "RECEIPT", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()

    if not AVAILABLE:
        with pytest.raises(OCRNotAvailableError):
            evidence_extractor.extract_evidence(
                png, make_input(filename="receipt-photo.png")
            )
    else:
        item = evidence_extractor.extract_evidence(
            png, make_input(filename="receipt-photo.png")
        )
        assert item.ocr_applied is True
        assert item.category is EvidenceCategory.PRODUCT_IMAGE
