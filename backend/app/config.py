import logging
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    APP_NAME: str = "ProofBridge AI API"
    APP_VERSION: str = "1.0.0"

    DATABASE_URL: str = Field(
        default="sqlite:///./proofbridge.db",
        repr=False
    )
    SECRET_KEY: str = Field(min_length=1, repr=False)
    ACCESS_TOKEN_MINUTES: int = Field(default=1440, gt=0)

    LOG_LEVEL: str = "INFO"

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    CORS_ALLOW_CREDENTIALS: bool = True

    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_BYTES: int = Field(default=10 * 1024 * 1024, gt=0)

    # Read-only PayPal transaction lookup. These credentials are never
    # returned by an endpoint, logged, or stored in the database.
    PAYPAL_CLIENT_ID: str | None = Field(default=None, repr=False)
    PAYPAL_CLIENT_SECRET: str | None = Field(default=None, repr=False)
    PAYPAL_API_BASE: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_TIMEOUT_SECONDS: float = Field(default=15.0, gt=0)

    FRONTEND_RETURN_URL: str = "http://localhost:5173/payment/return"
    FRONTEND_CANCEL_URL: str = "http://localhost:5173/payment/cancel"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @model_validator(mode="after")
    def validate_cors_configuration(self):
        if self.CORS_ALLOW_CREDENTIALS and "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS cannot include '*' while "
                "CORS_ALLOW_CREDENTIALS is enabled; list explicit origins."
            )

        return self

    @property
    def log_level(self) -> int:
        return logging.getLevelNamesMapping().get(
            self.LOG_LEVEL.upper(),
            logging.INFO
        )

    @property
    def upload_dir(self) -> Path:
        path = Path(self.UPLOAD_DIR)

        if not path.is_absolute():
            path = BASE_DIR / path

        return path.resolve()

    @property
    def paypal_configured(self) -> bool:
        return bool(
            self.PAYPAL_CLIENT_ID and self.PAYPAL_CLIENT_SECRET
        )

    @property
    def paypal_api_base(self) -> str:
        return self.PAYPAL_API_BASE.rstrip("/")

    @property
    def paypal_environment(self) -> str:
        return (
            "sandbox"
            if "sandbox" in self.paypal_api_base.lower()
            else "live"
        )


settings = Settings()
