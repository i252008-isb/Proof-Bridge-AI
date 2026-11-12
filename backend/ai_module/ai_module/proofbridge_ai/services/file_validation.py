"""File type detection and input validation.

Detection order: magic bytes (content is authoritative) -> content type
hint -> filename extension. Uploaded files are never executed; their bytes
are only inspected, decoded, or parsed by extraction libraries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import (
    FileTooLargeError,
    InputValidationError,
    UnsupportedFileTypeError,
)
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.schemas import FileType

if TYPE_CHECKING:  # pragma: no cover
    from proofbridge_ai.config import Settings

logger = get_logger("services.file_validation")

SUPPORTED_FORMATS_DESCRIPTION = (
    "PDF, DOCX, TXT, Markdown, CSV, PNG, JPEG, WEBP, and text-based source "
    "code files (PY, JS, TS, HTML, CSS, JSON, XML)"
)

EXTENSION_MAP: dict[str, FileType] = {
    ".pdf": FileType.PDF,
    ".docx": FileType.DOCX,
    ".txt": FileType.TXT,
    ".md": FileType.MARKDOWN,
    ".markdown": FileType.MARKDOWN,
    ".csv": FileType.CSV,
    ".png": FileType.PNG,
    ".jpg": FileType.JPEG,
    ".jpeg": FileType.JPEG,
    ".webp": FileType.WEBP,
    ".py": FileType.SOURCE_CODE,
    ".js": FileType.SOURCE_CODE,
    ".mjs": FileType.SOURCE_CODE,
    ".ts": FileType.SOURCE_CODE,
    ".tsx": FileType.SOURCE_CODE,
    ".html": FileType.SOURCE_CODE,
    ".htm": FileType.SOURCE_CODE,
    ".css": FileType.SOURCE_CODE,
    ".json": FileType.SOURCE_CODE,
    ".xml": FileType.SOURCE_CODE,
}

CONTENT_TYPE_MAP: dict[str, FileType] = {
    "application/pdf": FileType.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.DOCX,
    "text/plain": FileType.TXT,
    "text/markdown": FileType.MARKDOWN,
    "text/csv": FileType.CSV,
    "image/png": FileType.PNG,
    "image/jpeg": FileType.JPEG,
    "image/webp": FileType.WEBP,
    "application/json": FileType.SOURCE_CODE,
    "application/xml": FileType.SOURCE_CODE,
    "text/xml": FileType.SOURCE_CODE,
    "text/html": FileType.SOURCE_CODE,
    "text/x-python": FileType.SOURCE_CODE,
    "text/javascript": FileType.SOURCE_CODE,
    "application/javascript": FileType.SOURCE_CODE,
    "text/css": FileType.SOURCE_CODE,
}

_MAGIC_SIGNATURES: list[tuple[bytes, FileType]] = [
    (b"%PDF", FileType.PDF),
    (b"\x89PNG\r\n\x1a\n", FileType.PNG),
    (b"\xff\xd8\xff", FileType.JPEG),
    (b"PK\x03\x04", FileType.DOCX),
    (b"<?xml", FileType.SOURCE_CODE),
]


def _sniff_magic(file_bytes: bytes) -> FileType | None:
    if file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return FileType.WEBP
    for signature, file_type in _MAGIC_SIGNATURES:
        if file_bytes.startswith(signature):
            return file_type
    return None


def _from_extension(filename: str) -> FileType | None:
    if "." not in filename:
        return None
    extension = filename[filename.rfind(".") :].lower()
    return EXTENSION_MAP.get(extension)


def _from_content_type(content_type: str | None) -> FileType | None:
    if not content_type:
        return None
    normalized = content_type.split(";")[0].strip().lower()
    return CONTENT_TYPE_MAP.get(normalized)


def detect_file_type(
    filename: str,
    content_type: str | None = None,
    file_bytes: bytes | None = None,
) -> FileType:
    """Detect the FileType of an upload.

    Magic bytes win over the content type, which wins over the extension.

    Raises:
        UnsupportedFileTypeError: if no supported type can be determined.
    """
    if file_bytes:
        magic_type = _sniff_magic(file_bytes)
        if magic_type is not None:
            return magic_type
    mime_type = _from_content_type(content_type)
    if mime_type is not None:
        return mime_type
    extension_type = _from_extension(filename)
    if extension_type is not None:
        return extension_type
    raise UnsupportedFileTypeError(
        f"Unsupported file type for {filename!r}. Supported formats: "
        f"{SUPPORTED_FORMATS_DESCRIPTION}."
    )


def validate_file_input(
    file_bytes: bytes,
    filename: str,
    content_type: str | None = None,
    *,
    settings: "Settings | None" = None,
) -> FileType:
    """Validate an upload and return its detected FileType.

    Checks, in order: empty file, configured size limit, supported format.

    Raises:
        InputValidationError: empty file.
        FileTooLargeError: file exceeds PROOFBRIDGE_MAX_FILE_SIZE_BYTES.
        UnsupportedFileTypeError: unsupported format.
    """
    settings = settings or get_settings()
    if not file_bytes:
        raise InputValidationError(f"File {filename!r} is empty (0 bytes)")
    if len(file_bytes) > settings.max_file_size_bytes:
        raise FileTooLargeError(
            f"File {filename!r} is {len(file_bytes)} bytes, exceeding the "
            f"limit of {settings.max_file_size_bytes} bytes "
            f"(PROOFBRIDGE_MAX_FILE_SIZE_BYTES)",
            size=len(file_bytes),
            limit=settings.max_file_size_bytes,
        )
    file_type = detect_file_type(filename, content_type, file_bytes)
    logger.info(
        "validated file=%s type=%s size=%s",
        filename,
        file_type.value,
        len(file_bytes),
    )
    return file_type
