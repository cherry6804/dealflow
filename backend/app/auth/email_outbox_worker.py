
"""Standalone worker for encrypted authentication email delivery."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update

from app.auth.email_delivery import (
    send_password_reset_email,
    send_verification_email,
)
from app.auth.email_outbox import (
    EmailOutboxPayloadError,
    decrypt_email_payload,
)
from app.config import get_settings
from app.db.models.email_outbox_message import EmailOutboxMessage
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def process_one_email() -> bool:
    """Claim and process one job. Return False when none is ready."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claim_token = uuid.uuid4()

    with SessionLocal() as db:
        try:
            message = db.scalar(
                select(EmailOutboxMessage)
                .where(
                    or_(
                        (
                            (EmailOutboxMessage.status == "pending")
                            & (EmailOutboxMessage.available_at <= now)
                        ),
                        (
                            (EmailOutboxMessage.status == "processing")
                            & (EmailOutboxMessage.locked_until <= now)
                        ),
                    )
                )
                .order_by(
                    EmailOutboxMessage.available_at,
                    EmailOutboxMessage.created_at,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )

            if message is None:
                db.rollback()
                return False

            message.status = "processing"
            message.claim_token = claim_token
            message.locked_until = now + timedelta(
                seconds=settings.email_outbox_lease_seconds
            )
            message.attempts += 1
            message_id = message.id
            encrypted_payload = message.encrypted_payload
            db.commit()
        except Exception:
            db.rollback()
            raise

    def update_if_owned(values: dict[str, object]) -> bool:
        """Update only if this worker still owns the current claim."""
        with SessionLocal() as db:
            try:
                result = db.execute(
                    update(EmailOutboxMessage)
                    .where(
                        EmailOutboxMessage.id == message_id,
                        EmailOutboxMessage.status == "processing",
                        EmailOutboxMessage.claim_token == claim_token,
                    )
                    .values(**values)
                )
                db.commit()
                return result.rowcount == 1
            except Exception:
                db.rollback()
                raise

    try:
        payload = decrypt_email_payload(encrypted_payload)

        if payload["kind"] == "email_verification":
            send_verification_email(
                recipient=payload["recipient"],
                token=payload["token"],
            )
        elif payload["kind"] == "password_reset":
            send_password_reset_email(
                recipient=payload["recipient"],
                token=payload["token"],
            )
        else:
            # Defensive check; decrypt_email_payload already validates kind.
            raise EmailOutboxPayloadError("Unsupported email payload kind.")
    except EmailOutboxPayloadError:
        update_if_owned(
            {
                "status": "failed",
                "locked_until": None,
                "claim_token": None,
                "last_error": "invalid_encrypted_payload",
            }
        )
        logger.error("Email outbox payload validation failed")
        return True
    except Exception as exc:
        # Never log exception text: it may contain sensitive information.
        attempts = 0
        with SessionLocal() as db:
            try:
                current = db.scalar(
                    select(EmailOutboxMessage).where(
                        EmailOutboxMessage.id == message_id,
                        EmailOutboxMessage.status == "processing",
                        EmailOutboxMessage.claim_token == claim_token,
                    )
                )
                if current is not None:
                    attempts = current.attempts
            finally:
                db.close()

        if attempts == 0:
            # The claim expired or was replaced. Do not overwrite it.
            return True

        if attempts >= settings.email_outbox_max_attempts:
            values: dict[str, object] = {
                "status": "failed",
                "locked_until": None,
                "claim_token": None,
                "last_error": f"delivery_failed:{type(exc).__name__}",
            }
        else:
            values = {
                "status": "pending",
                "available_at": datetime.now(timezone.utc)
                + timedelta(seconds=min(2**attempts, 3600)),
                "locked_until": None,
                "claim_token": None,
                "last_error": f"delivery_failed:{type(exc).__name__}",
            }

        update_if_owned(values)
        logger.warning("Email outbox delivery attempt failed")
        return True

    sent = update_if_owned(
        {
            "status": "sent",
            "sent_at": datetime.now(timezone.utc),
            "locked_until": None,
            "claim_token": None,
            "last_error": None,
        }
    )

    if sent:
        logger.info("Email outbox job delivered")
    else:
        logger.warning("Email delivery completed after its claim expired")

    return True


def run_worker() -> None:
    """Poll for email jobs until the process is stopped."""
    settings = get_settings()
    logger.info("Email outbox worker started")

    while True:
        try:
            if not process_one_email():
                time.sleep(settings.email_outbox_poll_seconds)
        except KeyboardInterrupt:
            logger.info("Email outbox worker stopped")
            return
        except Exception:
            logger.error("Email outbox worker encountered an internal error")
            time.sleep(settings.email_outbox_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
