"""Server-side authentication session services for DealFlow."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.session import (
    generate_session_token,
    hash_session_token,
)
from app.db.models.auth_session import AuthSession
from app.db.models.user import User


def create_session(
    db: Session,
    user: User,
    expires_at: datetime,
) -> tuple[AuthSession, str]:
    """Create a server-side authentication session.

    Returns the persisted session and the raw session token. The raw token
    must only be delivered to the authenticated client and must never be
    persisted or logged.
    """
    token = generate_session_token()
    token_hash = hash_session_token(token)

    session = AuthSession(
        user=user,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return session, token


def get_active_session(
    db: Session,
    token: str,
) -> AuthSession | None:
    """Return an active session for a raw session token."""
    if not token:
        return None

    token_hash = hash_session_token(token)

    statement = select(AuthSession).where(
        AuthSession.token_hash == token_hash,
        AuthSession.revoked_at.is_(None),
    )

    session = db.scalar(statement)

    if session is None:
        return None

    now = datetime.now(timezone.utc)

    if session.expires_at <= now:
        return None

    return session


def revoke_session(
    db: Session,
    token: str,
) -> bool:
    """Revoke a session.

    Returns True when an existing, non-revoked session was found and
    revoked. Returns False when the session does not exist or is already
    revoked.
    """
    if not token:
        return False

    token_hash = hash_session_token(token)

    statement = select(AuthSession).where(
        AuthSession.token_hash == token_hash,
    )

    session = db.scalar(statement)

    if session is None or session.revoked_at is not None:
        return False

    session.revoked_at = datetime.now(timezone.utc)

    db.commit()

    return True