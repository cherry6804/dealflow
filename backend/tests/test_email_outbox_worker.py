
"""Tests for transactional email outbox worker behavior."""

import uuid
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.auth import email_outbox, email_outbox_worker as worker
from app.auth.email_outbox import enqueue_verification_email
from app.config import get_settings
from app.db.base import Base
from app.db.models.email_outbox_message import EmailOutboxMessage


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetime values to UTC for comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def setup_function() -> None:
    Base.metadata.create_all(engine)


def teardown_function() -> None:
    Base.metadata.drop_all(engine)


def configure_worker(monkeypatch, *, max_attempts: int = 8) -> None:
    """Configure worker and encryption independently of the developer .env."""
    original_settings = get_settings()
    test_settings = original_settings.model_copy(
        update={
            "email_outbox_encryption_key": SecretStr(
                Fernet.generate_key().decode("ascii")
            ),
            "email_outbox_max_attempts": max_attempts,
            "email_outbox_lease_seconds": 120,
            "email_outbox_poll_seconds": 0.01,
        }
    )

    monkeypatch.setattr(email_outbox, "get_settings", lambda: test_settings)
    monkeypatch.setattr(worker, "get_settings", lambda: test_settings)
    monkeypatch.setattr(worker, "SessionLocal", TestingSessionLocal)


def create_job(
    *,
    recipient: str = "worker@example.com",
    token: str = "test-verification-token",
) -> uuid.UUID:
    with TestingSessionLocal() as db:
        message = enqueue_verification_email(
            db,
            recipient=recipient,
            token=token,
        )
        db.commit()
        return message.id


def read_job(job_id: uuid.UUID) -> EmailOutboxMessage:
    with TestingSessionLocal() as db:
        message = db.get(EmailOutboxMessage, job_id)
        assert message is not None
        db.expunge(message)
        return message


def test_worker_delivers_email_and_marks_job_sent(monkeypatch) -> None:
    configure_worker(monkeypatch)
    job_id = create_job()

    delivered: list[dict[str, str]] = []
    monkeypatch.setattr(
        worker,
        "send_verification_email",
        lambda **kwargs: delivered.append(kwargs),
    )

    assert worker.process_one_email() is True

    job = read_job(job_id)
    assert job.status == "sent"
    assert job.attempts == 1
    assert job.sent_at is not None
    assert job.locked_until is None
    assert job.claim_token is None
    assert job.last_error is None

    assert delivered == [
        {
            "recipient": "worker@example.com",
            "token": "test-verification-token",
        }
    ]


def test_worker_retries_failed_delivery_with_backoff(monkeypatch) -> None:
    configure_worker(monkeypatch, max_attempts=3)
    job_id = create_job()

    def fail_delivery(**kwargs) -> None:
        raise RuntimeError("Provider failure with potentially sensitive details")

    monkeypatch.setattr(
        worker,
        "send_verification_email",
        fail_delivery,
    )

    before = datetime.now(timezone.utc)
    assert worker.process_one_email() is True

    job = read_job(job_id)
    assert job.status == "pending"
    assert job.attempts == 1
    assert as_utc(job.available_at) >= before + timedelta(seconds=1)
    assert job.locked_until is None
    assert job.claim_token is None
    assert job.last_error == "delivery_failed:RuntimeError"
    assert "potentially sensitive" not in job.last_error


def test_worker_marks_job_failed_after_maximum_attempts(
    monkeypatch,
) -> None:
    configure_worker(monkeypatch, max_attempts=1)
    job_id = create_job()

    def fail_delivery(**kwargs) -> None:
        raise RuntimeError("Provider failure")

    monkeypatch.setattr(
        worker,
        "send_verification_email",
        fail_delivery,
    )

    assert worker.process_one_email() is True

    job = read_job(job_id)
    assert job.status == "failed"
    assert job.attempts == 1
    assert job.locked_until is None
    assert job.claim_token is None
    assert job.last_error == "delivery_failed:RuntimeError"


def test_worker_marks_malformed_payload_failed(monkeypatch) -> None:
    configure_worker(monkeypatch)

    with TestingSessionLocal() as db:
        message = EmailOutboxMessage(
            encrypted_payload="not-a-valid-fernet-payload",
            status="pending",
            attempts=0,
            available_at=datetime.now(timezone.utc),
        )
        db.add(message)
        db.commit()
        job_id = message.id

    def should_not_send(**kwargs) -> None:
        raise AssertionError("Malformed payload must not be delivered.")

    monkeypatch.setattr(
        worker,
        "send_verification_email",
        should_not_send,
    )

    assert worker.process_one_email() is True

    job = read_job(job_id)
    assert job.status == "failed"
    assert job.locked_until is None
    assert job.claim_token is None
    assert job.last_error == "invalid_encrypted_payload"


def test_worker_does_not_overwrite_a_replaced_claim(monkeypatch) -> None:
    configure_worker(monkeypatch)
    job_id = create_job()
    replacement_claim = uuid.uuid4()

    def replace_claim_during_delivery(**kwargs) -> None:
        # Simulate another worker reclaiming the job while delivery is in
        # progress. SQLite does not test real concurrent row locking; this
        # specifically tests the claim-token ownership guard.
        with TestingSessionLocal() as db:
            message = db.get(EmailOutboxMessage, job_id)
            assert message is not None
            message.claim_token = replacement_claim
            message.locked_until = datetime.now(timezone.utc) + timedelta(
                seconds=120
            )
            db.commit()

    monkeypatch.setattr(
        worker,
        "send_verification_email",
        replace_claim_during_delivery,
    )

    assert worker.process_one_email() is True

    job = read_job(job_id)
    assert job.status == "processing"
    assert job.claim_token == replacement_claim
    assert job.locked_until is not None
    assert job.sent_at is None


def test_worker_returns_false_when_no_job_is_ready(monkeypatch) -> None:
    configure_worker(monkeypatch)

    assert worker.process_one_email() is False


def test_worker_reclaims_an_expired_processing_lease(monkeypatch) -> None:
    configure_worker(monkeypatch)
    job_id = create_job()
    old_claim = uuid.uuid4()

    with TestingSessionLocal() as db:
        message = db.get(EmailOutboxMessage, job_id)
        assert message is not None
        message.status = "processing"
        message.claim_token = old_claim
        message.locked_until = datetime.now(timezone.utc) - timedelta(
            seconds=5
        )
        db.commit()

    delivered: list[dict[str, str]] = []
    monkeypatch.setattr(
        worker,
        "send_verification_email",
        lambda **kwargs: delivered.append(kwargs),
    )

    assert worker.process_one_email() is True

    job = read_job(job_id)
    assert job.status == "sent"
    assert job.claim_token is None
    assert job.attempts == 1
    assert len(delivered) == 1
