
"""Encrypted transactional outbox for verification email jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.email_outbox_message import EmailOutboxMessage


class EmailOutboxConfigurationError(RuntimeError):
    """Raised when email outbox encryption is not configured."""


class EmailOutboxPayloadError(RuntimeError):
    """Raised when an encrypted outbox payload cannot be decoded."""


def _fernet() -> Fernet:
    """Return the configured authenticated-encryption instance."""
    settings = get_settings()
    secret = settings.email_outbox_encryption_key

    if secret is None or not secret.get_secret_value().strip():
        raise EmailOutboxConfigurationError(
            "EMAIL_OUTBOX_ENCRYPTION_KEY is not configured."
        )

    try:
        return Fernet(secret.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise EmailOutboxConfigurationError(
            "EMAIL_OUTBOX_ENCRYPTION_KEY is invalid."
        ) from exc


def enqueue_verification_email(
    db: Session,
    *,
    recipient: str,
    token: str,
    now: datetime | None = None,
) -> EmailOutboxMessage:
    """Add an encrypted verification email job to the current transaction."""
    if not recipient.strip() or not token:
        raise ValueError("Recipient and verification token are required.")

    payload = {
        "kind": "email_verification",
        "recipient": recipient,
        "token": token,
    }
    encrypted_payload = _fernet().encrypt(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    message = EmailOutboxMessage(
        encrypted_payload=encrypted_payload,
        status="pending",
        attempts=0,
        available_at=now or datetime.now(timezone.utc),
    )
    db.add(message)
    db.flush()
    return message


def decrypt_email_payload(
    encrypted_payload: str,
) -> dict[str, str]:
    """Decrypt and validate a queued email payload."""
    try:
        plaintext = _fernet().decrypt(
            encrypted_payload.encode("ascii")
        )
        payload = json.loads(plaintext.decode("utf-8"))
    except (
        InvalidToken,
        UnicodeEncodeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise EmailOutboxPayloadError(
            "Email outbox payload is invalid or cannot be decrypted."
        ) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "email_verification"
        or not isinstance(payload.get("recipient"), str)
        or not payload["recipient"].strip()
        or not isinstance(payload.get("token"), str)
        or not payload["token"]
    ):
        raise EmailOutboxPayloadError(
            "Email outbox payload has an invalid structure."
        )

    return payload


def mark_email_sent(
    db: Session,
    message: EmailOutboxMessage,
    *,
    now: datetime | None = None,
) -> None:
    """Mark a successfully delivered message."""
    message.status = "sent"
    message.sent_at = now or datetime.now(timezone.utc)
    message.locked_until = None
    message.last_error = None


def mark_email_failed(
    db: Session,
    message: EmailOutboxMessage,
    *,
    error: str,
    now: datetime | None = None,
) -> None:
    """Record a failed attempt and schedule retry or terminal failure."""
    settings = get_settings()
    current_time = now or datetime.now(timezone.utc)

    message.attempts += 1
    message.locked_until = None
    message.last_error = error[:500]

    if message.attempts >= settings.email_outbox_max_attempts:
        message.status = "failed"
        return

    # Exponential backoff: 2, 4, 8... seconds, capped at one hour.
    delay_seconds = min(2 ** message.attempts, 3600)
    from datetime import timedelta

    message.status = "pending"
    message.available_at = current_time + timedelta(
        seconds=delay_seconds
    )
