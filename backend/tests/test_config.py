from app.config import Settings


def test_default_settings(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(
        _env_file="",
    )

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


def test_database_url_can_be_overridden(monkeypatch) -> None:
    database_url = "postgresql+psycopg://test:test@localhost:5432/testdb"

    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = Settings(
        _env_file="",
    )

    assert settings.database_url == database_url


def test_auth_settings_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SESSION_LIFETIME_HOURS", "24")
    monkeypatch.setenv("AUTH_COOKIE_NAME", "custom_session")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_COOKIE_HTTPONLY", "false")
    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "strict")
    monkeypatch.setenv("AUTH_COOKIE_PATH", "/api")

    settings = Settings(
        _env_file="",
    )

    assert settings.auth_session_lifetime_hours == 24
    assert settings.auth_cookie_name == "custom_session"
    assert settings.auth_cookie_secure is True
    assert settings.auth_cookie_httponly is False
    assert settings.auth_cookie_samesite == "strict"
    assert settings.auth_cookie_path == "/api"