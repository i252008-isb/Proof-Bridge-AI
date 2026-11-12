"""Text cleaning and normalization without destroying meaning.

The original extracted text is always kept; this module produces the cleaned
variant. Prose gets whitespace collapsed; source code and CSV get minimal
normalization because indentation and spacing carry meaning there.
"""

from __future__ import annotations

import re

# Unicode punctuation that OCR or word processors commonly emit, mapped to
# ASCII equivalents. Letters and other symbols are left untouched.
_PUNCTUATION_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\ufeff": "",
        "\u3000": " ",
    }
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_text(text: str, *, preserve_whitespace: bool = False) -> str:
    """Clean extracted text.

    Handles: unusual line endings, excessive whitespace, repeated blank
    lines, stray control characters, and common OCR/word-processor
    punctuation artifacts.

    Args:
        text: The raw extracted text.
        preserve_whitespace: If True (source code, CSV), indentation and
            inline spacing are kept; only line endings, trailing spaces, and
            blank-line runs are cleaned.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = text.translate(_PUNCTUATION_MAP)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    if preserve_whitespace:
        return text.strip("\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text to ``max_chars`` characters.

    Returns:
        (text, truncated) — truncated is True when the text was cut.
    """
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
