"""OCR for screenshots and scanned documents (Tesseract via pytesseract).

pytesseract is imported lazily so the dependency stays optional. When
Tesseract is missing, a clear OCRNotAvailableError explains the installation
requirement — OCR is never silently skipped or faked.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from proofbridge_ai.config import get_settings
from proofbridge_ai.exceptions import DocumentExtractionError, OCRNotAvailableError
from proofbridge_ai.logging_utils import get_logger
from proofbridge_ai.schemas import ExtractionWarning, OCRResult

if TYPE_CHECKING:  # pragma: no cover
    from proofbridge_ai.config import Settings

logger = get_logger("services.ocr")

_TESSERACT_INSTALL_HINT = (
    "Install the Tesseract OCR engine "
    "(Windows: https://github.com/UB-Mannheim/tesseract/wiki, "
    "macOS: `brew install tesseract`, Linux: `apt install tesseract-ocr`), "
    "then `pip install -e \"ai_module[ocr]\"`, or set "
    "PROOFBRIDGE_TESSERACT_CMD to the tesseract binary path."
)


def is_ocr_available(settings: "Settings | None" = None) -> tuple[bool, str | None]:
    """Return (available, reason). Never raises."""
    settings = settings or get_settings()
    try:
        import pytesseract
    except ImportError:
        return False, (
            "The pytesseract package is not installed. Install it with: "
            'pip install -e "ai_module[ocr]"'
        )
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False, _TESSERACT_INSTALL_HINT
    return True, None


def extract_text_from_image(
    image_bytes: bytes,
    filename: str = "",
    settings: "Settings | None" = None,
) -> OCRResult:
    """Run OCR over a single image and return the recognized text.

    Applies EXIF rotation (practical orientation handling), downscales very
    large images instead of failing, and converts to RGB before OCR.

    Args:
        image_bytes: Raw image content (PNG, JPEG, WEBP, ...).
        filename: Optional original filename for logging.
        settings: Optional Settings override.

    Returns:
        OCRResult with the recognized text and any warnings.

    Raises:
        OCRNotAvailableError: pytesseract or the Tesseract engine is missing
            (message includes installation guidance).
        DocumentExtractionError: the bytes are not a readable image or OCR
            failed at runtime.
    """
    settings = settings or get_settings()
    available, reason = is_ocr_available(settings)
    if not available:
        raise OCRNotAvailableError(f"OCR unavailable: {reason}")

    import pytesseract

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        image = ImageOps.exif_transpose(image)
    except (Image.UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise DocumentExtractionError(
            f"Could not read image {filename!r}: invalid or unsupported image data"
        ) from exc

    warnings: list[ExtractionWarning] = []
    width, height = image.size
    pixels = width * height
    if pixels > settings.max_image_pixels:
        scale = (settings.max_image_pixels / pixels) ** 0.5
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        warnings.append(
            ExtractionWarning(
                code="image_downscaled",
                message=(
                    f"Image downscaled from {pixels} to about "
                    f"{new_size[0] * new_size[1]} pixels "
                    f"(PROOFBRIDGE_MAX_IMAGE_PIXELS={settings.max_image_pixels})"
                ),
            )
        )

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    try:
        text = pytesseract.image_to_string(image, lang=settings.ocr_language).strip()
    except Exception as exc:
        raise DocumentExtractionError(
            f"OCR failed for {filename!r}: {type(exc).__name__}"
        ) from exc

    if not text:
        warnings.append(
            ExtractionWarning(
                code="no_text_recognized",
                message="No readable text was recognized in the image",
            )
        )
    logger.info("ocr done file=%s chars=%s", filename or "<unnamed>", len(text))
    return OCRResult(
        text=text,
        engine="tesseract",
        language=settings.ocr_language,
        warnings=warnings,
    )
