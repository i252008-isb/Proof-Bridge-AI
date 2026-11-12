import pytest

from _ocr_env import tesseract_available
from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import (
    DocumentExtractionError,
    FileTooLargeError,
    InputValidationError,
    OCRNotAvailableError,
    UnsupportedFileTypeError,
)
from proofbridge_ai.schemas import FileType
from proofbridge_ai.services import document_extractor

AVAILABLE = tesseract_available()


def test_pdf_extraction_preserves_page_order(sample_pdf_bytes):
    result = document_extractor.extract_document(sample_pdf_bytes, "agreement.pdf")
    assert result.success is True
    assert result.file_type is FileType.PDF
    assert result.extraction_method == "pymupdf"
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert result.pages[0].text == "Page one text"
    assert result.pages[1].text == "Page two text"
    assert result.pages[2].text == "Page three text"
    assert result.extracted_text.index("Page one") < result.extracted_text.index("Page three")
    assert result.is_ocr_used is False
    assert result.warnings == []
    assert result.normalized_text is not None


def test_extract_document_text_returns_plain_string(sample_pdf_bytes):
    result = document_extractor.extract_document(sample_pdf_bytes, "agreement.pdf")
    assert isinstance(result.extracted_text, str)
    assert "Page two text" in result.extracted_text


def test_empty_pdf_reports_empty_pages(empty_pdf_bytes):
    result = document_extractor.extract_document(empty_pdf_bytes, "empty.pdf")
    assert result.success is True
    assert len(result.pages) == 1
    assert result.pages[0].is_empty is True
    assert any(w.code == "no_text_extracted" for w in result.warnings)


def test_pdf_page_limit(monkeypatch, sample_pdf_bytes):
    monkeypatch.setenv("PROOFBRIDGE_MAX_PDF_PAGES", "2")
    get_settings.cache_clear()
    result = document_extractor.extract_document(sample_pdf_bytes, "agreement.pdf")
    assert len(result.pages) == 2
    assert any(w.code == "page_limit_exceeded" for w in result.warnings)


def test_docx_extracts_headings_paragraphs_and_tables(sample_docx_bytes):
    result = document_extractor.extract_document(sample_docx_bytes, "agreement.docx")
    assert result.file_type is FileType.DOCX
    assert result.extraction_method == "python-docx"
    assert "# Store Return Policy" in result.extracted_text
    assert "Customers may request a refund for damaged products reported" in result.extracted_text
    assert "Condition | Outcome" in result.extracted_text
    assert "Damaged on arrival | Refund eligible" in result.extracted_text


def test_txt_extraction_keeps_original_and_normalized():
    result = document_extractor.extract_document(b"Hello   world.\n\n\n\nExcess  whitespace!", "note.txt")
    assert result.file_type is FileType.TXT
    assert result.extraction_method == "builtin"
    assert "Hello   world." in result.extracted_text
    assert "Hello world." in result.normalized_text
    assert "\n\n\n\n" not in result.normalized_text


@pytest.mark.parametrize(
    ("filename", "expected_type"),
    [
        ("readme.md", FileType.MARKDOWN),
        ("data.csv", FileType.CSV),
        ("main.py", FileType.SOURCE_CODE),
        ("app.js", FileType.SOURCE_CODE),
        ("style.css", FileType.SOURCE_CODE),
        ("config.json", FileType.SOURCE_CODE),
    ],
)
def test_text_file_types(filename, expected_type):
    result = document_extractor.extract_document(b"simple content", filename)
    assert result.file_type is expected_type


def test_source_code_whitespace_preserved_in_normalized():
    result = document_extractor.extract_document(b"def f():\n    return 1", "main.py")
    assert "    return 1" in result.normalized_text


def test_unsupported_extension_raises():
    with pytest.raises(UnsupportedFileTypeError) as exc_info:
        document_extractor.extract_document(b"some data", "file.xyz")
    assert "Supported formats" in str(exc_info.value)


def test_empty_file_raises():
    with pytest.raises(InputValidationError):
        document_extractor.extract_document(b"", "file.txt")


def test_oversized_file_raises(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_MAX_FILE_SIZE_BYTES", "10")
    get_settings.cache_clear()
    with pytest.raises(FileTooLargeError) as exc_info:
        document_extractor.extract_document(b"x" * 20, "big.txt")
    assert exc_info.value.size == 20
    assert exc_info.value.limit == 10


def test_invalid_pdf_raises_extraction_error():
    with pytest.raises(DocumentExtractionError):
        document_extractor.extract_document(b"this is definitely not a pdf", "broken.pdf")


def test_invalid_docx_raises_extraction_error():
    with pytest.raises(DocumentExtractionError):
        document_extractor.extract_document(b"PK\x03\x04garbage-not-a-real-zip", "broken.docx")


def test_scanned_pdf_handling(scanned_pdf_bytes):
    result = document_extractor.extract_document(scanned_pdf_bytes, "scan.pdf")
    if AVAILABLE:
        assert result.is_ocr_used is True
        assert result.pages[0].ocr_used is True
        assert "INVOICE" in result.pages[0].text
    else:
        assert result.is_ocr_used is False
        assert result.pages[0].is_empty is True
        assert any(w.code == "scanned_page_no_ocr" for w in result.warnings)


def test_image_document_uses_ocr(sample_image_bytes):
    if not AVAILABLE:
        with pytest.raises(OCRNotAvailableError):
            document_extractor.extract_document(sample_image_bytes, "shot.png")
    else:
        result = document_extractor.extract_document(sample_image_bytes, "shot.png")
        assert result.file_type is FileType.PNG
        assert result.extraction_method == "tesseract"
        assert result.is_ocr_used is True
        assert "LOGIN" in result.extracted_text
