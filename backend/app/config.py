
"""Application configuration for DealFlow."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "DealFlow API"
    app_version: str = "0.1.0"
    database_url: str = (
        "postgresql+psycopg://postgres@localhost:5432/dealflow"
    )

    # Authentication and session settings
    auth_session_lifetime_hours: int = 12
    auth_cookie_name: str = "dealflow_session"
    auth_cookie_secure: bool = False
    auth_cookie_httponly: bool = True
    auth_cookie_samesite: str = "lax"
    auth_cookie_path: str = "/"

    # Email verification
    email_verification_token_lifetime_minutes: int = Field(
        default=30,
        gt=0,
        le=1440,
    )
    email_verification_resend_cooldown_seconds: int = Field(
        default=60,
        gt=0,
    )
    email_verification_max_resends_per_hour: int = Field(
        default=5,
        gt=0,
    )
    email_verification_base_url: str = "http://localhost:5173"
    email_verification_delivery_mode: str = "development"
    email_verification_outbox_dir: Path = (
        BASE_DIR / "var" / "private_mailbox"
    )

    # Email outbox encryption.
    # Configure EMAIL_OUTBOX_ENCRYPTION_KEY in the root .env.
    # Do not log or expose this secret.
    email_outbox_encryption_key: SecretStr | None = None
    email_outbox_batch_size: int = Field(default=20, gt=0, le=500)
    email_outbox_max_attempts: int = Field(default=8, gt=0, le=100)
    email_outbox_lease_seconds: int = Field(default=120, gt=0)
    email_outbox_poll_seconds: float = Field(default=2.0, gt=0, le=300)

    # Private local storage for uploaded import source files.
    upload_storage_dir: Path = BASE_DIR / "var" / "private_uploads"
    upload_max_file_size_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
    )

    # Private object storage for business documents.
    object_storage_backend: str = "local"
    object_storage_dir: Path = BASE_DIR / "var" / "private_objects"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
