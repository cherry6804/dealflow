from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "DealFlow API"
    app_version: str = "0.1.0"
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/dealflow"

    auth_session_lifetime_hours: int = 12
    auth_cookie_name: str = "dealflow_session"
    auth_cookie_secure: bool = False
    auth_cookie_httponly: bool = True
    auth_cookie_samesite: str = "lax"
    auth_cookie_path: str = "/"

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