
"""Application configuration for DealFlow."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "DealFlow API"
    app_version: str = "0.1.0"
    app_environment: Literal[
        "development", "test", "staging", "production"
    ] = "development"

    database_url: str = (
        "postgresql+psycopg://postgres@localhost:5432/dealflow"
    )
    cors_allowed_origins: str = "http://localhost:5174"

    # Existing authentication and session settings.
    auth_session_lifetime_hours: int = Field(default=12, gt=0, le=720)
    auth_cookie_name: str = "dealflow_session"
    auth_cookie_secure: bool = False
    auth_cookie_httponly: bool = True
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_path: str = "/"

    # SIBVO single sign-on.
    # Include the API prefix in the base URL.
    # Example: http://localhost:8000/api/v1
    sso_sibvo_base_url: str = "http://localhost:8000/api/v1"

    sso_dealsflo_client_id: str = "dealsflo"
    sso_dealsflo_client_secret: SecretStr | None = Field(
        default=None,
        repr=False,
    )
    sso_dealsflo_redirect_uri: str = (
        "http://localhost:5174/sso/callback"
    )

    sso_http_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=30,
    )
    sso_revalidation_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
    )

    sso_flow_cookie_name: str = "dealsflo_sso_flow"
    sso_flow_cookie_secure: bool = False
    sso_flow_cookie_path: str = "/api/v1/sso"
    sso_flow_cookie_max_age_seconds: int = Field(
        default=300,
        ge=60,
        le=600,
    )

    # Email verification.
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

    # SMTP.
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = Field(default=587, gt=0, le=65535)
    email_smtp_username: SecretStr | None = None
    email_smtp_password: SecretStr | None = Field(
        default=None,
        repr=False,
    )
    email_from_address: str = ""
    email_smtp_timeout_seconds: int = Field(
        default=20,
        gt=0,
        le=120,
    )

    # Password recovery.
    password_reset_token_lifetime_minutes: int = Field(
        default=30,
        gt=0,
        le=1440,
    )
    password_reset_request_cooldown_seconds: int = Field(
        default=60,
        gt=0,
    )
    password_reset_max_requests_per_hour: int = Field(
        default=5,
        gt=0,
    )

    # Transactional outbox dispatch.
    outbox_max_attempts: int = Field(default=5, ge=1, le=50)
    outbox_base_backoff_seconds: int = Field(default=30, ge=1, le=3600)
    outbox_max_backoff_seconds: int = Field(default=3600, ge=1, le=86400)
    outbox_lease_seconds: int = Field(default=300, ge=10, le=3600)
    outbox_batch_size: int = Field(default=50, ge=1, le=500)

    # Encrypted transactional email outbox.
    email_outbox_encryption_key: SecretStr | None = Field(
        default=None,
        repr=False,
    )
    email_outbox_batch_size: int = Field(
        default=20,
        gt=0,
        le=500,
    )
    email_outbox_max_attempts: int = Field(
        default=8,
        gt=0,
        le=100,
    )
    email_outbox_lease_seconds: int = Field(
        default=120,
        gt=0,
    )
    email_outbox_poll_seconds: float = Field(
        default=2.0,
        gt=0,
        le=300,
    )

    # Private storage.
    upload_storage_dir: Path = BASE_DIR / "var" / "private_uploads"
    upload_max_file_size_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
    )
    object_storage_backend: Literal["local", "s3"] = "local"
    object_storage_dir: Path = BASE_DIR / "var" / "private_objects"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    @field_validator(
        "app_name",
        "app_version",
        "auth_cookie_name",
        "sso_dealsflo_client_id",
        "sso_dealsflo_redirect_uri",
        "sso_sibvo_base_url",
        "sso_flow_cookie_name",
        "sso_flow_cookie_path",
    )
    @classmethod
    def reject_blank_required_strings(cls, value: str) -> str:
        """Reject empty configuration values."""
        value = value.strip()
        if not value:
            raise ValueError("This setting must not be blank.")
        return value

    @field_validator("sso_sibvo_base_url")
    @classmethod
    def validate_sibvo_base_url(cls, value: str) -> str:
        """Require a valid HTTP(S) URL with no query or fragment."""
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "SSO_SIBVO_BASE_URL must be a valid HTTP(S) URL "
                "without credentials, query parameters, or a fragment."
            )

        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        """Accept only explicit HTTP(S) origins, never wildcard CORS."""
        origins = [origin.strip().rstrip("/") for origin in value.split(",")]
        origins = [origin for origin in origins if origin]
        if not origins or "*" in origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit origins.")

        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS must be a comma-separated list "
                    "of origins without paths, credentials, or wildcards."
                )

        return ",".join(dict.fromkeys(origins))

    @property
    def cors_origins(self) -> list[str]:
        """Return validated CORS origins for Starlette middleware."""
        return self.cors_allowed_origins.split(",")

    @field_validator("sso_dealsflo_redirect_uri")
    @classmethod
    def validate_sso_redirect_uri(cls, value: str) -> str:
        """Validate the registered SSO callback URL."""
        value = value.strip()
        parsed = urlsplit(value)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError(
                "SSO_DEALSFLO_REDIRECT_URI must be a valid HTTP(S) URL."
            )

        return value

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        """Validate cookie, SSO, and production security requirements."""

        if (
            self.auth_cookie_samesite == "none"
            and not self.auth_cookie_secure
        ):
            raise ValueError(
                "SameSite=None cookies require Secure cookies."
            )

        if self.sso_flow_cookie_path != "/api/v1/sso":
            raise ValueError(
                "SSO flow cookies must be scoped to /api/v1/sso."
            )

        if (
            self.sso_flow_cookie_name == self.auth_cookie_name
        ):
            raise ValueError(
                "SSO flow and authentication cookies must have "
                "different names."
            )

        if self.app_environment == "production":
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires PostgreSQL.")

            database_url = urlsplit(self.database_url)
            database_query = dict(
                item.split("=", 1)
                for item in database_url.query.split("&")
                if "=" in item
            )
            if (
                database_url.hostname not in {"localhost", "127.0.0.1", "::1"}
                and database_query.get("sslmode")
                not in {"require", "verify-ca", "verify-full"}
            ):
                raise ValueError(
                    "Production PostgreSQL connections outside localhost "
                    "must require TLS with sslmode=require or stronger."
                )

            if not self.auth_cookie_secure:
                raise ValueError(
                    "AUTH_COOKIE_SECURE must be true in production."
                )

            if not self.auth_cookie_httponly:
                raise ValueError(
                    "AUTH_COOKIE_HTTPONLY must be true in production."
                )

            if not self.sso_flow_cookie_secure:
                raise ValueError(
                    "SSO_FLOW_COOKIE_SECURE must be true in production."
                )

            if not self.sso_sibvo_base_url.startswith("https://"):
                raise ValueError(
                    "SIBVO SSO must use HTTPS in production."
                )

            if not self.sso_dealsflo_redirect_uri.startswith("https://"):
                raise ValueError(
                    "SSO_DEALSFLO_REDIRECT_URI must use HTTPS "
                    "in production."
                )

            if not self.sso_dealsflo_client_secret:
                raise ValueError(
                    "SSO_DEALSFLO_CLIENT_SECRET is required in production."
                )

            if not self.sso_dealsflo_client_secret.get_secret_value().strip():
                raise ValueError(
                    "SSO_DEALSFLO_CLIENT_SECRET must not be blank."
                )

            if any(
                not origin.startswith("https://")
                for origin in self.cors_origins
            ):
                raise ValueError(
                    "Production CORS origins must use HTTPS."
                )

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


# Expose this only if the existing application imports it directly.
# Remove this line if your project initializes settings elsewhere.
settings = get_settings()
