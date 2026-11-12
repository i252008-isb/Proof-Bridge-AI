import pytest

from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import FileTooLargeError, InputValidationError, UnsupportedFileTypeError
from proofbridge_ai.schemas import FileType
from proofbridge_ai.services.file_validation import detect_file_type, validate_file_input


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("agreement.pdf", FileType.PDF),
        ("agreement.docx", FileType.DOCX),
        ("notes.txt", FileType.TXT),
        ("readme.md", FileType.MARKDOWN),
        ("readme.markdown", FileType.MARKDOWN),
        ("data.csv", FileType.CSV),
        ("photo.png", FileType.PNG),
        ("photo.jpg", FileType.JPEG),
        ("photo.jpeg", FileType.JPEG),
        ("photo.WEBP", FileType.WEBP),
        ("main.py", FileType.SOURCE_CODE),
        ("app.js", FileType.SOURCE_CODE),
        ("app.ts", FileType.SOURCE_CODE),
        ("index.html", FileType.SOURCE_CODE),
        ("style.css", FileType.SOURCE_CODE),
        ("config.json", FileType.SOURCE_CODE),
        ("data.xml", FileType.SOURCE_CODE),
    ],
)
def test_detect_by_extension(filename, expected):
    assert detect_file_type(filename, None, b"placeholder") is expected


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("x.bin", "application/pdf", FileType.PDF),
        ("x", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", FileType.DOCX),
        ("x", "text/plain", FileType.TXT),
        ("x", "text/csv", FileType.CSV),
        ("x", "image/png", FileType.PNG),
        ("x", "image/jpeg", FileType.JPEG),
        ("x", "image/webp", FileType.WEBP),
        ("x", "text/html", FileType.SOURCE_CODE),
        ("x", "text/javascript", FileType.SOURCE_CODE),
    ],
)
def test_detect_by_content_type(filename, content_type, expected):
    assert detect_file_type(filename, content_type, b"placeholder") is expected


@pytest.mark.parametrize(
    ("content", "filename", "expected"),
    [
        (b"%PDF-1.7 rest of pdf", "renamed.txt", FileType.PDF),
        (b"\x89PNG\r\n\x1a\nrest", "renamed.txt", FileType.PNG),
        (b"\xff\xd8\xff\xe0rest", "renamed.bin", FileType.JPEG),
        (b"PK\x03\x04rest", "renamed.bin", FileType.DOCX),
        (b"RIFF\x00\x00\x00\x00WEBPrest", "renamed.bin", FileType.WEBP),
        (b"<?xml version='1.0'?>", "renamed.bin", FileType.SOURCE_CODE),
    ],
)
def test_magic_bytes_win_over_extension(content, filename, expected):
    assert detect_file_type(filename, None, content) is expected


def test_unsupported_extension_raises_structured_error():
    with pytest.raises(UnsupportedFileTypeError) as exc_info:
        detect_file_type("file.xyz", None, b"data")
    assert "Supported formats" in str(exc_info.value)


def test_empty_file_raises_input_validation_error():
    with pytest.raises(InputValidationError):
        validate_file_input(b"", "file.txt")


def test_oversized_file_raises_file_too_large(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_MAX_FILE_SIZE_BYTES", "5")
    get_settings.cache_clear()
    with pytest.raises(FileTooLargeError) as exc_info:
        validate_file_input(b"123456", "file.txt")
    assert exc_info.value.size == 6
    assert exc_info.value.limit == 5


def test_valid_input_returns_file_type():
    assert validate_file_input(b"hello world", "file.txt") is FileType.TXT
