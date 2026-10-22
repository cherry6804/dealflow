
"""Tests for authentication cookie security configuration."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_development_allows_http_cookie_configuration() -> None:
    settings = Settings(
        _env_file=None,
        app_environment="development",
        auth_cookie_secure=False,
    )

    assert settings.auth_cookie_secure is False
    assert settings.auth_cookie_httponly is True
    assert settings.auth_cookie_samesite == "lax"


def test_production_requires_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="AUTH_COOKIE_SECURE"):
        Settings(
            _env_file=None,
            app_environment="production",
            auth_cookie_secure=False,
        )


def test_production_accepts_secure_cookie() -> None:
    settings = Settings(
        _env_file=None,
        app_environment="production",
        auth_cookie_secure=True,
    )

    assert settings.auth_cookie_secure is True
    assert settings.auth_cookie_httponly is True


def test_production_rejects_non_httponly_cookie() -> None:
    with pytest.raises(ValidationError, match="AUTH_COOKIE_HTTPONLY"):
        Settings(
            _env_file=None,
            app_environment="production",
            auth_cookie_secure=True,
            auth_cookie_httponly=False,
        )


def test_session_lifetime_must_be_positive_and_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_session_lifetime_hours=0)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_session_lifetime_hours=721)


def test_samesite_none_requires_secure_cookie_in_all_environments() -> None:
    for environment in ("development", "test", "staging", "production"):
        with pytest.raises(
            ValidationError,
            match="SameSite=None cookies require Secure cookies",
        ):
            Settings(
                _env_file=None,
                app_environment=environment,
                auth_cookie_secure=False,
                auth_cookie_samesite="none",
            )


def test_samesite_none_is_allowed_with_secure_cookie() -> None:
    settings = Settings(
        _env_file=None,
        app_environment="development",
        auth_cookie_secure=True,
        auth_cookie_samesite="none",
    )

    assert settings.auth_cookie_secure is True
    assert settings.auth_cookie_samesite == "none"
