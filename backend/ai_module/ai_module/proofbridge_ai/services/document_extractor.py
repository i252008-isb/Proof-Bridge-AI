"""Document text extraction for agreements and evidence files.

Supported formats: PDF (PyMuPDF, page-by-page, scanned-page OCR fallback),
DOCX (python-docx, paragraphs + headings + tables), TXT/Markdown/CSV and
text-based source code, and images (via OCR).

Uploaded files are never executed. Extracted text is treated as untrusted
data, is never logged in full, and never appears in exception messages.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import DocumentExtractionError
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.schemas import (
    DocumentExtractionResult,
    ExtractedPage,
    ExtractionWarning,
    FileType,
)
from proofbridge_ai.services import ocr_service
from proofbridge_ai.services.file_validation import validate_file_input
from proofbridge_ai.services.text_normalizer import normalize_text, truncate_text

if TYPE_CHECKING:  # pragma: no cover
    from proofbridge_ai.config import Settings

logger = get_logger("services.document_extractor")

_PDF_ZOOM = 2  # render scale for OCR of scanned pages


def extract_document(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
    settings: "Settings | None" = None,
) -> DocumentExtractionResult:
    """Extract text from a supported document.

    Args:
        file_bytes: Raw file content as bytes.
        filename: Original filename, used for format detection.
        content_type: Optional MIME type hint.
        settings: Optional Settings override (defaults to process settings).

    Returns:
        DocumentExtractionResult with the original extracted text, the
        normalized variant, per-page detail for PDFs, the extraction method,
        and any warnings. ``success`` is False only when extraction could not
        complete at all; partial results carry warnings instead.

    Raises:
        InputValidationError: empty file.
        FileTooLargeError: file exceeds PROOFBRIDGE_MAX_FILE_SIZE_BYTES.
        UnsupportedFileTypeError: unsupported format.
        DocumentExtractionError: unreadable/corrupt file or OCR runtime failure.
        OCRNotAvailableError: image input (or scanned PDF page) requires OCR
            but Tesseract is missing.
    """
    settings = settings or get_settings()
    file_type = validate_file_input(file_bytes, filename, content_type, settings=settings)
    logger.info(
        "extracting file=%s type=%s size=%s",
        filename,
        file_type.value,
        len(file_bytes),
    )

    if file_type is FileType.PDF:
        result = _extract_pdf(file_bytes, filename, settings)
    elif file_type is FileType.DOCX:
        result = _extract_docx(file_bytes, filename)
    elif file_type in (FileType.PNG, FileType.JPEG, FileType.WEBP):
        result = _extract_image(file_bytes, filename, file_type, settings)
    else:
        result = _extract_text_file(file_bytes, filename, file_type)

    _finalize(result, settings)
    logger.info(
        "extracted file=%s chars=%s pages=%s warnings=%s",
        filename,
        len(result.extracted_text),
        len(result.pages),
        len(result.warnings),
    )
    return result


def extract_document_text(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
    settings: "Settings | None" = None,
) -> str:
    """Convenience wrapper returning only the extracted text.

    Prefer extract_document when warnings or per-page structure matter.
    """
    return extract_document(file_bytes, filename, content_type, settings).extracted_text


def _finalize(result: DocumentExtractionResult, settings: "Settings") -> None:
    text, was_truncated = truncate_text(result.extracted_text, settings.max_document_chars)
    if was_truncated:
        result.extracted_text = text
        result.warnings.append(
            ExtractionWarning(
                code="text_truncated",
                message=(
                    f"Extracted text was truncated to {settings.max_document_chars} "
                    "characters (PROOFBRIDGE_MAX_DOCUMENT_CHARS)"
                ),
            )
        )
    if not result.extracted_text.strip() and not any(
        w.code in ("no_text_extracted", "no_text_recognized") for w in result.warnings
    ):
        result.warnings.append(
            ExtractionWarning(
                code="no_text_extracted", message="No text could be extracted from the file"
            )
        )
    preserve_whitespace = result.file_type in (FileType.SOURCE_CODE, FileType.CSV)
    result.normalized_text = normalize_text(
        result.extracted_text, preserve_whitespace=preserve_whitespace
    )


def _extract_pdf(
    file_bytes: bytes, filename: str, settings: "Settings"
) -> DocumentExtractionResult:
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # older PyMuPDF installs

    try:
        document = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise DocumentExtractionError(
            f"Could not open PDF {filename!r}: invalid or corrupt PDF"
        ) from exc

    warnings: list[ExtractionWarning] = []
    pages: list[ExtractedPage] = []
    ocr_used_any = False
    try:
        if document.needs_pass:
            raise DocumentExtractionError(f"PDF {filename!r} is password-protected")
        if not document.is_pdf:
            raise DocumentExtractionError(f"File {filename!r} is not a valid PDF")

        total_pages = document.page_count
        pages_to_read = min(total_pages, settings.max_pdf_pages)
        if total_pages > settings.max_pdf_pages:
            warnings.append(
                ExtractionWarning(
                    code="page_limit_exceeded",
                    message=(
                        f"Only the first {settings.max_pdf_pages} of {total_pages} "
                        "pages were processed (PROOFBRIDGE_MAX_PDF_PAGES)"
                    ),
                )
            )

        ocr_available, ocr_reason = ocr_service.is_ocr_available(settings)
        for index in range(pages_to_read):
            page = document.load_page(index)
            page_number = index + 1
            text = page.get_text("text")
            ocr_used = False
            if not text.strip() and page.get_images(full=True):
                if ocr_available:
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(_PDF_ZOOM, _PDF_ZOOM))
                    ocr_result = ocr_service.extract_text_from_image(
                        pixmap.tobytes("png"),
                        filename=f"{filename} page {page_number}",
                        settings=settings,
                    )
                    text = ocr_result.text
                    ocr_used = True
                    ocr_used_any = True
                    warnings.extend(ocr_result.warnings)
                else:
                    warnings.append(
                        ExtractionWarning(
                            code="scanned_page_no_ocr",
                            message=(
                                f"Page {page_number} appears to be a scanned image and "
                                f"OCR is unavailable: {ocr_reason}"
                            ),
                            page_number=page_number,
                        )
                    )
            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=text.strip(),
                    is_empty=not text.strip(),
                    ocr_used=ocr_used,
                )
            )
    finally:
        document.close()

    extracted_text = "\n\n".join(page.text for page in pages)
    return DocumentExtractionResult(
        filename=filename,
        file_type=FileType.PDF,
        extracted_text=extracted_text,
        pages=pages,
        extraction_method="pymupdf",
        is_ocr_used=ocr_used_any,
        warnings=warnings,
    )


def _extract_docx(file_bytes: bytes, filename: str) -> DocumentExtractionResult:
    try:
        import docx
    except ImportError as exc:
        raise DocumentExtractionError(
            "python-docx is not installed (required for DOCX extraction)"
        ) from exc
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(file_bytes))
    except Exception as exc:
        raise DocumentExtractionError(
            f"Could not open DOCX {filename!r}: invalid or corrupt document"
        ) from exc

    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        tag = getattr(child, "tag", "")
        if tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = (paragraph.style.name or "").lower()
            if style_name.startswith("heading") or style_name == "title":
                blocks.append(f"# {text}")
            else:
                blocks.append(text)
        elif tag.endswith("}tbl"):
            table = Table(child, document)
            rows: list[str] = []
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                rows.append(" | ".join(cells))
            if rows:
                blocks.append("\n".join(rows))

    return DocumentExtractionResult(
        filename=filename,
        file_type=FileType.DOCX,
        extracted_text="\n".join(blocks),
        pages=[],
        extraction_method="python-docx",
        warnings=[],
    )


def _extract_image(
    file_bytes: bytes, filename: str, file_type: FileType, settings: "Settings"
) -> DocumentExtractionResult:
    ocr_result = ocr_service.extract_text_from_image(
        file_bytes, filename=filename, settings=settings
    )
    return DocumentExtractionResult(
        filename=filename,
        file_type=file_type,
        extracted_text=ocr_result.text,
        pages=[],
        extraction_method="tesseract",
        is_ocr_used=True,
        warnings=list(ocr_result.warnings),
    )


def _extract_text_file(
    file_bytes: bytes, filename: str, file_type: FileType
) -> DocumentExtractionResult:
    text, warnings = _decode_bytes(file_bytes)
    return DocumentExtractionResult(
        filename=filename,
        file_type=file_type,
        extracted_text=text,
        pages=[],
        extraction_method="builtin",
        warnings=warnings,
    )


def _decode_bytes(file_bytes: bytes) -> tuple[str, list[ExtractionWarning]]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return file_bytes.decode(encoding), []
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace"), [
        ExtractionWarning(
            code="lossy_decoding",
            message=(
                "The file is not valid UTF-8/CP1252 text; undecodable bytes "
                "were replaced with '?'"
            ),
        )
    ]
