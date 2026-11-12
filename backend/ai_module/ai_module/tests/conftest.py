"""Shared fixtures: isolated environment, demo-mode settings,
and generated sample documents."""

import io
import os

import pytest
from PIL import Image, ImageDraw

from proofbridge_ai.config import get_settings
from proofbridge_ai.providers import (
    _default_embeddings_provider,
    _default_llm_provider,
    _default_vision_provider,
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch):
    """Scrub PROOFBRIDGE_* env vars and clear config/provider caches per test."""
    for key in list(os.environ):
        if key.startswith("PROOFBRIDGE_"):
            monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    _default_llm_provider.cache_clear()
    _default_embeddings_provider.cache_clear()
    _default_vision_provider.cache_clear()
    yield
    get_settings.cache_clear()
    _default_llm_provider.cache_clear()
    _default_embeddings_provider.cache_clear()
    _default_vision_provider.cache_clear()


@pytest.fixture()
def settings_demo(monkeypatch):
    """Settings with demo mode on; even openai providers resolve to mocks."""
    monkeypatch.setenv("PROOFBRIDGE_DEMO_MODE", "true")
    monkeypatch.setenv("PROOFBRIDGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PROOFBRIDGE_EMBEDDINGS_PROVIDER", "openai")
    monkeypatch.setenv("PROOFBRIDGE_VISION_PROVIDER", "openai")
    get_settings.cache_clear()
    return get_settings()


# --------------------------------------------------------------- samples


def _png_bytes(text: str, size: tuple[int, int] = (500, 120)) -> bytes:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 40), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def sample_pdf_bytes():
    """Three-page PDF with plain text on each page."""
    import pymupdf

    document = pymupdf.open()
    for label in ("Page one text", "Page two text", "Page three text"):
        page = document.new_page()
        page.insert_text((72, 72), label)
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture()
def empty_pdf_bytes():
    """One-page PDF with no text and no images."""
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture()
def scanned_pdf_bytes():
    """One-page PDF containing only an embedded image (simulated scan)."""
    import pymupdf

    png = _png_bytes("INVOICE 2026-001")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(pymupdf.Rect(0, 0, 500, 120), stream=png)
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture()
def sample_docx_bytes():
    """DOCX with a heading, a paragraph, and a table."""
    import docx

    document = docx.Document()
    document.add_heading("Store Return Policy", level=1)
    document.add_paragraph(
        "Customers may request a refund for damaged products reported "
        "within seven days of delivery."
    )
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Condition"
    table.cell(0, 1).text = "Outcome"
    table.cell(1, 0).text = "Damaged on arrival"
    table.cell(1, 1).text = "Refund eligible"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def sample_image_bytes():
    """PNG image containing readable text (for OCR tests)."""
    return _png_bytes("LOGIN PAGE SCREENSHOT")
