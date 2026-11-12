"""Centralized configuration via environment variables (PROOFBRIDGE_* prefix).

Reads from the process environment and an optional local .env file.
Never contains hardcoded secrets; keys are stored as pydantic SecretStr.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from proofbridge_ai.exceptions import ConfigurationError


class Settings(BaseSettings):
    """All runtime configuration for the proofbridge_ai package."""

    model_config = SettingsConfigDict(
        env_prefix="PROOFBRIDGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "production", "demo"] = "development"
    demo_mode: bool = False
    log_level: str = "INFO"

    llm_provider: Literal["mock", "openai"] = "mock"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0

    embeddings_provider: Literal["mock", "openai"] = "mock"
    embeddings_api_key: SecretStr = SecretStr("")
    embeddings_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"

    vision_provider: Literal["mock", "openai"] = "mock"
    vision_api_key: SecretStr = SecretStr("")
    vision_base_url: str = "https://api.openai.com/v1"
    vision_model: str = "gpt-4o-mini"

    ocr_enabled: bool = False
    tesseract_cmd: str = ""
    ocr_language: str = "eng"

    max_file_size_bytes: int = 10_485_760
    max_pdf_pages: int = 100
    max_image_pixels: int = 25_000_000
    max_document_chars: int = 200_000
    http_timeout_seconds: float = 60.0
    max_retries: int = 2

    similarity_supported_threshold: float = 0.60
    similarity_partial_threshold: float = 0.40
    similarity_max_candidates: int = 5

    @model_validator(mode="after")
    def _validate_values(self) -> "Settings":
        if not (0.0 <= self.similarity_partial_threshold <= 1.0):
            raise ValueError(
                "PROOFBRIDGE_SIMILARITY_PARTIAL_THRESHOLD must be within [0, 1], "
                f"got {self.similarity_partial_threshold}"
            )
        if not (0.0 <= self.similarity_supported_threshold <= 1.0):
            raise ValueError(
                "PROOFBRIDGE_SIMILARITY_SUPPORTED_THRESHOLD must be within [0, 1], "
                f"got {self.similarity_supported_threshold}"
            )
        if self.similarity_supported_threshold < self.similarity_partial_threshold:
            raise ValueError(
                "PROOFBRIDGE_SIMILARITY_SUPPORTED_THRESHOLD "
                f"({self.similarity_supported_threshold}) must be >= "
                f"PROOFBRIDGE_SIMILARITY_PARTIAL_THRESHOLD ({self.similarity_partial_threshold})"
            )
        if self.max_document_chars <= 0:
            raise ValueError("PROOFBRIDGE_MAX_DOCUMENT_CHARS must be positive")
        if self.max_file_size_bytes <= 0:
            raise ValueError("PROOFBRIDGE_MAX_FILE_SIZE_BYTES must be positive")
        if self.max_pdf_pages <= 0:
            raise ValueError("PROOFBRIDGE_MAX_PDF_PAGES must be positive")
        if self.max_image_pixels <= 0:
            raise ValueError("PROOFBRIDGE_MAX_IMAGE_PIXELS must be positive")
        if self.http_timeout_seconds <= 0:
            raise ValueError("PROOFBRIDGE_HTTP_TIMEOUT_SECONDS must be positive")
        if self.max_retries < 0:
            raise ValueError("PROOFBRIDGE_MAX_RETRIES must not be negative")
        if self.similarity_max_candidates < 1:
            raise ValueError("PROOFBRIDGE_SIMILARITY_MAX_CANDIDATES must be >= 1")
        return self

    def llm_key_present(self) -> bool:
        return bool(self.llm_api_key.get_secret_value())

    def embeddings_key_present(self) -> bool:
        return bool(self.embeddings_api_key.get_secret_value())

    def vision_key_present(self) -> bool:
        return bool(self.vision_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance.

    Raises:
        ConfigurationError: if any PROOFBRIDGE_* environment value is invalid.
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid PROOFBRIDGE_* configuration: {exc}") from exc
