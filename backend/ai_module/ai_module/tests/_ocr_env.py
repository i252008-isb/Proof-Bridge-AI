"""Environment capability checks used for conditional OCR tests."""


def tesseract_available() -> bool:
    """True when pytesseract is installed AND the Tesseract binary works."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
