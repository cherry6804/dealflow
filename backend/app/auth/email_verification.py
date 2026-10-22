
"""Email verification token utilities and lifecycle services."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.email_verification_token import EmailVerificationToken
from app.db.models.user import User


TOKEN_BYTES = 32


def generate_verification_token() -> str:
    """Generate a cryptographically secure verification token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_verification_token(token: str) -> str:
    """Return the SHA-256 hash of a verification token."""
    if not token:
        raise ValueError("Verification token cannot be empty.")

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_verification_token(
    db: Session,
    *,
    user: User,
    now: datetime | None = None,
) -> tuple[EmailVerificationToken, str]:
    """Create a token record and return it with the raw token.

    The caller owns the transaction and must commit or roll back.
    Raw tokens must only be passed to the email-delivery adapter.
    """
    settings = get_settings()
    issued_at = now or datetime.now(timezone.utc)

    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)

    raw_token = generate_verification_token()

    record = EmailVerificationToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_verification_token(raw_token),
        expires_at=issued_at
        + timedelta(
            minutes=settings.email_verification_token_lifetime_minutes
        ),
    )

    db.add(record)
    db.flush()

    return record, raw_token


def consume_verification_token(
    db: Session,
    *,
    token: str,
    now: datetime | None = None,
) -> User | None:
    """Consume a valid, unexpired token and verify its user.

    Returns None for malformed, unknown, expired, or previously used
    tokens. The caller owns the transaction.
    """
    if not token or len(token) > 512:
        return None

    try:
        token_hash = hash_verification_token(token)
    except ValueError:
        return None

    current_time = now or datetime.now(timezone.utc)

    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    statement = (
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == token_hash)
        .with_for_update()
    )

    record = db.scalar(statement)

    if record is None or record.used_at is not None:
        return None

    expires_at = record.expires_at

    # SQLite may return naive datetimes even for timezone-aware columns.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= current_time:
        return None

    user = db.scalar(
        select(User).where(User.id == record.user_id).with_for_update()
    )

    if user is None or not user.is_active:
        return None

    record.used_at = current_time
    user.is_email_verified = True

    db.flush()

    return user
