"""Exception hierarchy for ProofBridge AI.

Every error raised by this package derives from ProofBridgeAIError, so callers
(the FastAPI backend included) can catch a single base class.
"""

from __future__ import annotations


class ProofBridgeAIError(Exception):
    """Base class for every error raised by the proofbridge_ai package."""


class ConfigurationError(ProofBridgeAIError):
    """Invalid, missing, or contradictory configuration."""


class InputValidationError(ProofBridgeAIError):
    """Caller-supplied arguments failed validation (bad bytes, filename, models)."""


class FileTooLargeError(InputValidationError):
    """The uploaded file exceeds the configured size limit.

    Attributes:
        size: actual file size in bytes.
        limit: configured maximum size in bytes.
    """

    def __init__(self, message: str, *, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(message)


class UnsupportedFileTypeError(ProofBridgeAIError):
    """A file's type or extension is not supported for the requested operation."""


class DocumentExtractionError(ProofBridgeAIError):
    """A document could not be parsed or extracted."""


class OCRNotAvailableError(DocumentExtractionError):
    """OCR was requested but the Tesseract engine is not installed or configured."""


class ProviderError(ProofBridgeAIError):
    """An LLM or embeddings provider call failed.

    Attributes:
        provider: name of the failing provider (never contains secrets).
        status_code: HTTP status if the failure was an HTTP error, else None.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class ProviderResponseValidationError(ProviderError):
    """The provider's response could not be validated against the expected schema."""


class AnalysisError(ProofBridgeAIError):
    """An error occurred during similarity, classification, or report generation."""


class ServiceNotImplementedError(ProofBridgeAIError, NotImplementedError):
    """A service exists as an interface stub and will be implemented in a later phase."""
