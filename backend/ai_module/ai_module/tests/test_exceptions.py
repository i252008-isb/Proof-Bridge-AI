import pytest

from proofbridge_ai import (
    AnalysisError,
    ConfigurationError,
    DocumentExtractionError,
    InputValidationError,
    OCRNotAvailableError,
    ProofBridgeAIError,
    ProviderError,
    ProviderResponseValidationError,
    ServiceNotImplementedError,
    UnsupportedFileTypeError,
)


def test_all_errors_derive_from_base():
    for cls in (
        ConfigurationError,
        InputValidationError,
        UnsupportedFileTypeError,
        DocumentExtractionError,
        OCRNotAvailableError,
        ProviderError,
        ProviderResponseValidationError,
        AnalysisError,
        ServiceNotImplementedError,
    ):
        assert issubclass(cls, ProofBridgeAIError)


def test_ocr_error_is_extraction_error():
    assert issubclass(OCRNotAvailableError, DocumentExtractionError)


def test_provider_validation_error_is_provider_error():
    assert issubclass(ProviderResponseValidationError, ProviderError)


def test_provider_error_attributes():
    error = ProviderError("boom", provider="openai", status_code=429)
    assert error.provider == "openai"
    assert error.status_code == 429
    assert str(error) == "boom"


def test_provider_error_defaults():
    error = ProviderError("boom", provider="mock")
    assert error.status_code is None


def test_service_not_implemented_is_not_implemented_error():
    error = ServiceNotImplementedError("later")
    assert isinstance(error, NotImplementedError)
    with pytest.raises(ProofBridgeAIError):
        raise error
