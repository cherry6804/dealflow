
"""Password-reset token lifecycle services."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.password_reset_token import PasswordResetToken


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    """Normalize database timestamps to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_password_reset_token(token: str) -> str:
    """Hash a raw password-reset token before database lookup/storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset_token(
    db: Session,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> tuple[PasswordResetToken, str]:
    """Create a hashed, expiring reset token.

    The caller owns the transaction and must commit or roll back.
    The raw token is returned only for delivery to the user.
    """
    settings = get_settings()
    issued_at = _normalize_datetime(now or _utc_now())

    raw_token = secrets.token_urlsafe(32)
    token_record = PasswordResetToken(
        user_id=user_id,
        token_hash=hash_password_reset_token(raw_token),
        created_at=issued_at,
        expires_at=issued_at
        + timedelta(minutes=settings.password_reset_token_lifetime_minutes),
    )

    db.add(token_record)
    db.flush()

    return token_record, raw_token


def consume_password_reset_token(
    db: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> PasswordResetToken | None:
    """Validate and consume a reset token within the caller's transaction.

    A row lock prevents two concurrent transactions from successfully
    consuming the same token on databases that support SELECT FOR UPDATE.
    The caller must commit the transaction after applying the password reset.
    """
    if not token:
        return None

    current_time = _normalize_datetime(now or _utc_now())
    token_hash = hash_password_reset_token(token)

    statement = (
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    record = db.scalar(statement)

    if record is None or record.used_at is not None:
        return None

    if _normalize_datetime(record.expires_at) <= current_time:
        return None

    record.used_at = current_time
    db.flush()

    return record


def invalidate_password_reset_tokens(
    db: Session,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Invalidate all outstanding reset tokens for a user.

    The caller owns the transaction and must commit or roll back.
    """
    current_time = _normalize_datetime(now or _utc_now())

    statement = (
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .with_for_update()
    )
    records = db.scalars(statement).all()

    for record in records:
        record.used_at = current_time

    db.flush()
    return len(records)
