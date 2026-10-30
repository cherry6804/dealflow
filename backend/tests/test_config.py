"""Tests for application configuration."""

from app.config import BASE_DIR, Settings


def test_default_settings(monkeypatch) -> None:
    """Verify application settings and storage defaults."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_DIR", raising=False)

    settings = Settings(_env_file="")

    assert settings.app_name == "DealFlow API"
    assert settings.app_version == "0.1.0"
    assert settings.database_url == (
        "postgresql+psycopg://postgres@localhost:5432/dealflow"
    )

    assert settings.auth_session_lifetime_hours == 12
    assert settings.auth_cookie_name == "dealflow_session"
    assert settings.auth_cookie_secure is False
    assert settings.auth_cookie_httponly is True
    assert settings.auth_cookie_samesite == "lax"
    assert settings.auth_cookie_path == "/"

    assert settings.upload_storage_dir == (
        BASE_DIR / "var" / "private_uploads"
    )
    assert settings.upload_max_file_size_bytes == 10 * 1024 * 1024

    assert settings.object_storage_backend == "local"
    assert settings.object_storage_dir == (
        BASE_DIR / "var" / "private_objects"
    )


def test_database_url_can_be_overridden(monkeypatch) -> None:
    """Allow the database URL to be configured through the environment."""
    database_url = "postgresql+psycopg://test:test@localhost:5432/testdb"
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = Settings(_env_file="")

    assert settings.database_url == database_url


def test_auth_settings_can_be_overridden(monkeypatch) -> None:
    """Allow authentication settings to be configured."""
    monkeypatch.setenv("AUTH_SESSION_LIFETIME_HOURS", "24")
    monkeypatch.setenv("AUTH_COOKIE_NAME", "custom_session")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_COOKIE_HTTPONLY", "false")
    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "strict")
    monkeypatch.setenv("AUTH_COOKIE_PATH", "/api")

    settings = Settings(_env_file="")

    assert settings.auth_session_lifetime_hours == 24
    assert settings.auth_cookie_name == "custom_session"
    assert settings.auth_cookie_secure is True
    assert settings.auth_cookie_httponly is False
    assert settings.auth_cookie_samesite == "strict"
    assert settings.auth_cookie_path == "/api"


def test_object_storage_settings_can_be_overridden(monkeypatch, tmp_path) -> None:
    """Allow the object storage provider and directory to be configured."""
    storage_dir = tmp_path / "custom-private-storage"

    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("OBJECT_STORAGE_DIR", str(storage_dir))

    settings = Settings(_env_file="")

    assert settings.object_storage_backend == "local"
    assert settings.object_storage_dir == storage_dir