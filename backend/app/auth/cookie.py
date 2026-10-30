"""Authentication session cookie helpers for DealFlow."""

from datetime import datetime

from fastapi import Request, Response

from app.config import Settings


def set_session_cookie(
    response: Response,
    token: str,
    expires_at: datetime,
    settings: Settings,
) -> None:
    """Set the authenticated session cookie."""
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        expires=expires_at,
        httponly=settings.auth_cookie_httponly,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=settings.auth_cookie_path,
    )


def get_session_cookie(
    request: Request,
    settings: Settings,
) -> str | None:
    """Read the authenticated session cookie from a request."""
    return request.cookies.get(settings.auth_cookie_name)


def clear_session_cookie(
    response: Response,
    settings: Settings,
) -> None:
    """Clear the authenticated session cookie."""
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=settings.auth_cookie_httponly,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=settings.auth_cookie_path,
    )