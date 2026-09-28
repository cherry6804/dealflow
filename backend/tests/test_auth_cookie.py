from datetime import datetime, timezone

from fastapi import Request, Response

from app.auth.cookie import (
    clear_session_cookie,
    get_session_cookie,
    set_session_cookie,
)
from app.config import Settings


def test_set_session_cookie_sets_expected_attributes() -> None:
    settings = Settings(_env_file="")

    response = Response()
    expires_at = datetime.now(timezone.utc)

    set_session_cookie(
        response,
        "test-session-token",
        expires_at,
        settings,
    )

    set_cookie_header = response.headers["set-cookie"]

    assert "dealflow_session=test-session-token" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header
    assert "Path=/" in set_cookie_header
    assert "Secure" not in set_cookie_header


def test_secure_cookie_can_be_enabled() -> None:
    settings = Settings(
        _env_file="",
        auth_cookie_secure=True,
    )

    response = Response()
    expires_at = datetime.now(timezone.utc)

    set_session_cookie(
        response,
        "test-session-token",
        expires_at,
        settings,
    )

    set_cookie_header = response.headers["set-cookie"]

    assert "Secure" in set_cookie_header


def test_get_session_cookie_reads_configured_cookie() -> None:
    settings = Settings(_env_file="")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (
                    b"cookie",
                    b"dealflow_session=test-session-token",
                )
            ],
        }
    )

    assert get_session_cookie(request, settings) == "test-session-token"


def test_get_session_cookie_returns_none_when_missing() -> None:
    settings = Settings(_env_file="")

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )

    assert get_session_cookie(request, settings) is None


def test_clear_session_cookie_expires_cookie() -> None:
    settings = Settings(_env_file="")

    response = Response()

    clear_session_cookie(
        response,
        settings,
    )

    set_cookie_header = response.headers["set-cookie"]

    assert "dealflow_session=" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header
    assert "Path=/" in set_cookie_header