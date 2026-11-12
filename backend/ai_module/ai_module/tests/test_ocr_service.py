import io

import pytest
from PIL import Image, ImageDraw

from _ocr_env import tesseract_available
from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import DocumentExtractionError, OCRNotAvailableError
from proofbridge_ai.schemas import OCRResult
from proofbridge_ai.services import ocr_service

AVAILABLE = tesseract_available()


def _image_bytes(text="INVOICE 123", size=(500, 120)):
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 40), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_invalid_image_raises_extraction_error():
    with pytest.raises(DocumentExtractionError):
        ocr_service.extract_text_from_image(b"definitely not an image", "fake.png")


@pytest.mark.skipif(AVAILABLE, reason="Tesseract is installed on this machine")
def test_ocr_unavailable_raises_clear_error():
    with pytest.raises(OCRNotAvailableError) as exc_info:
        ocr_service.extract_text_from_image(_image_bytes(), "shot.png")
    message = str(exc_info.value)
    assert "Tesseract" in message or "pytesseract" in message


@pytest.mark.skipif(AVAILABLE, reason="Tesseract is installed on this machine")
def test_is_ocr_available_returns_false_with_reason():
    available, reason = ocr_service.is_ocr_available()
    assert available is False
    assert reason


@pytest.mark.skipif(not AVAILABLE, reason="Tesseract is not installed")
def test_ocr_extracts_readable_text():
    result = ocr_service.extract_text_from_image(_image_bytes("HELLO PROOFBRIDGE"), "shot.png")
    assert isinstance(result, OCRResult)
    assert result.success is True
    assert result.engine == "tesseract"
    assert "PROOFBRIDGE" in result.text


@pytest.mark.skipif(not AVAILABLE, reason="Tesseract is not installed")
def test_is_ocr_available_returns_true():
    available, reason = ocr_service.is_ocr_available()
    assert available is True
    assert reason is None


@pytest.mark.skipif(not AVAILABLE, reason="Tesseract is not installed")
def test_large_image_downscaled_with_warning(monkeypatch):
    monkeypatch.setenv("PROOFBRIDGE_MAX_IMAGE_PIXELS", "1000")
    get_settings.cache_clear()
    result = ocr_service.extract_text_from_image(_image_bytes(size=(100, 100)))
    assert any(w.code == "image_downscaled" for w in result.warnings)
