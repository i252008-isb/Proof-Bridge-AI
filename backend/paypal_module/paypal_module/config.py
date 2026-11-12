"""
Configuration module for the PayPal integration.

Loads sandbox credentials and settings from .env lazily.
Does not raise at import time; validates and raises on first call to `get_settings()`.
"""

import os
from pathlib import Path
from typing import NamedTuple, Optional
from dotenv import load_dotenv

# Search for .env (first check inside paypal_module/, then in project root)
_current_dir = Path(__file__).resolve().parent
_root_dir = _current_dir.parent

_env_path = _current_dir / ".env"
if not _env_path.exists():
    _env_path = _root_dir / ".env"

load_dotenv(dotenv_path=_env_path)


class Settings(NamedTuple):
    client_id: str
    client_secret: str
    base_url: str
    return_url: Optional[str] = None
    cancel_url: Optional[str] = None


def get_missing_settings() -> list[str]:
    """Return a list of required environment variables that are missing or empty."""
    missing = []
    if not (os.getenv("PAYPAL_CLIENT_ID")):
        missing.append("PAYPAL_CLIENT_ID")
    if not (os.getenv("PAYPAL_CLIENT_SECRET")):
        missing.append("PAYPAL_CLIENT_SECRET")
    if not (os.getenv("PAYPAL_BASE_URL") or os.getenv("PAYPAL_API_BASE")):
        missing.append("PAYPAL_BASE_URL (or PAYPAL_API_BASE)")
    return missing


def get_settings() -> Settings:
    """
    Validate and return the PayPal configuration settings.

    Raises:
        ValueError: If any required setting is missing.
    """
    try:
        from app.config import settings as backend_settings
        client_id = backend_settings.PAYPAL_CLIENT_ID or os.getenv("PAYPAL_CLIENT_ID", "")
        client_secret = backend_settings.PAYPAL_CLIENT_SECRET or os.getenv("PAYPAL_CLIENT_SECRET", "")
        base_url = (
            backend_settings.PAYPAL_API_BASE
            or os.getenv("PAYPAL_BASE_URL")
            or "https://api-m.sandbox.paypal.com"
        )
        return_url = backend_settings.FRONTEND_RETURN_URL or os.getenv("FRONTEND_RETURN_URL")
        cancel_url = backend_settings.FRONTEND_CANCEL_URL or os.getenv("FRONTEND_CANCEL_URL")
    except Exception:
        client_id = os.getenv("PAYPAL_CLIENT_ID", "")
        client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
        base_url = os.getenv("PAYPAL_BASE_URL") or os.getenv("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")
        return_url = os.getenv("FRONTEND_RETURN_URL")
        cancel_url = os.getenv("FRONTEND_CANCEL_URL")

    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    base_url = (base_url or "").strip().rstrip("/")

    missing = []
    if not client_id:
        missing.append("PAYPAL_CLIENT_ID")
    if not client_secret:
        missing.append("PAYPAL_CLIENT_SECRET")
    if not base_url:
        missing.append("PAYPAL_BASE_URL")

    if missing:
        raise ValueError(
            f"Missing required PayPal configuration in .env: {', '.join(missing)}.\n"
            f"Please ensure a '.env' file exists with all required keys."
        )

    return Settings(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        return_url=return_url,
        cancel_url=cancel_url,
    )
