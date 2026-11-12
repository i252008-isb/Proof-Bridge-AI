"""Logging helpers enforcing the package-wide rule:

never log document contents, prompts, evidence excerpts, or secrets.
Log only ids, filenames, sizes, counts, status codes, and provider names.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from proofbridge_ai.config import Settings


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``proofbridge_ai`` namespace."""
    return logging.getLogger(f"proofbridge_ai.{name}")


def configure_logging(settings: "Settings") -> None:
    """Attach a stdout handler for CLI scripts.

    The library itself never adds handlers: when embedded in a backend, the
    backend owns logging configuration and this function should not be used.
    """
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def redact(text: str) -> str:
    """Return a size + content hash instead of the text itself."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"len={len(text)} sha256={digest}"


def describe_bytes(data: bytes) -> str:
    """Return a size-only description of binary content."""
    return f"size={len(data)} bytes"
