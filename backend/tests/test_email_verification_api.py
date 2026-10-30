
"""Integration tests for email verification and resend behavior."""

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.api import auth as auth_api
from app.api.auth import router as auth_router
from app.auth import email_outbox
from app.auth.email_outbox import decrypt_email_payload
from app.auth.email_verification import (
    create_verification_token,
    hash_verification_token,
)
from app.auth.password import hash_password
from app.config import get_settings
from app.db.base import Base
from app.db.models.auth_session import AuthSession
from app.db.models.email_outbox_message import EmailOutboxMessage
from app.db.models.email_verification_token import EmailVerificationToken
from app.db.models.user import User
from app.db.session import get_db_session
from app.errors import register_error_handlers


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


def override_get_db_session() -> Generator[Session, None, None]:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


api_test_app = FastAPI()
register_error_handlers(api_test_app)
api_test_app.include_router(auth_router)
api_test_app.dependency_overrides[get_db_session] = override_get_db_session

client = TestClient(api_test_app)


def setup_function() -> None:
    Base.metadata.create_all(engine)


def teardown_function() -> None:
    Base.metadata.drop_all(engine)
    client.cookies.clear()


def teardown_module() -> None:
    api_test_app.dependency_overrides.clear()


def configure_outbox_encryption(monkeypatch) -> None:
    """Use a test-only encryption key instead of relying on the local .env."""
    original_settings = get_settings()
    test_settings = original_settings.model_copy(
        update={
            "email_outbox_encryption_key": SecretStr(
                Fernet.generate_key().decode("ascii")
            )
        }
    )
    monkeypatch.setattr(email_outbox, "get_settings", lambda: test_settings)


def create_user(
    *,
    email: str = "pending@example.com",
    verified: bool = False,
) -> User:
    with TestingSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            email=email,
            display_name="Verification Test",
            password_hash=hash_password("StrongPassword!123"),
            is_active=True,
            is_email_verified=verified,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def create_token(
    user: User,
    *,
    created_at: datetime | None = None,
    expired: bool = False,
) -> str:
    with TestingSessionLocal() as db:
        db_user = db.get(User, user.id)
        assert db_user is not None

        issued_at = created_at or datetime.now(timezone.utc)
        _, raw_token = create_verification_token(
            db,
            user=db_user,
            now=issued_at,
        )

        if expired:
            record = db.scalar(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.token_hash
                    == hash_verification_token(raw_token)
                )
            )
            assert record is not None
            record.expires_at = issued_at - timedelta(seconds=1)

        db.commit()
        return raw_token


def age_latest_token(user: User, *, age: timedelta) -> None:
    """Age the latest token so resend cooldown behavior is deterministic."""
    with TestingSessionLocal() as db:
        record = db.scalar(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .order_by(EmailVerificationToken.created_at.desc())
            .limit(1)
        )
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - age
        db.commit()


def test_valid_token_verifies_user_and_cannot_be_reused() -> None:
    user = create_user()
    token = create_token(user)

    first = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )
    assert first.status_code == 200

    with TestingSessionLocal() as db:
        refreshed_user = db.get(User, user.id)
        assert refreshed_user is not None
        assert refreshed_user.is_email_verified is True

        record = db.scalar(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash
                == hash_verification_token(token)
            )
        )
        assert record is not None
        assert record.used_at is not None

    second = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )
    assert second.status_code == 400


def test_expired_token_is_rejected() -> None:
    user = create_user()
    token = create_token(user, expired=True)

    response = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )

    assert response.status_code == 400

    with TestingSessionLocal() as db:
        refreshed_user = db.get(User, user.id)
        assert refreshed_user is not None
        assert refreshed_user.is_email_verified is False


def test_unknown_token_is_rejected() -> None:
    response = client.post(
        "/api/v1/auth/verify-email",
        json={"token": "unknown-token"},
    )

    assert response.status_code == 400


def test_unverified_user_cannot_login_or_create_session() -> None:
    user = create_user(verified=False)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "StrongPassword!123",
        },
    )

    assert response.status_code == 403
    assert "dealflow_session" not in response.cookies

    with TestingSessionLocal() as db:
        assert db.scalar(
            select(AuthSession).where(AuthSession.user_id == user.id)
        ) is None


def test_unverified_user_cannot_use_existing_session() -> None:
    user = create_user(verified=False)

    from app.auth.service import create_session

    with TestingSessionLocal() as db:
        db_user = db.get(User, user.id)
        assert db_user is not None
        _, raw_session_token = create_session(
            db=db,
            user=db_user,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.commit()

    client.cookies.set("dealflow_session", raw_session_token)
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 403


def test_resend_unknown_email_returns_generic_response() -> None:
    response = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": "unknown@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == auth_api.RESEND_GENERIC_MESSAGE

    with TestingSessionLocal() as db:
        assert db.scalar(select(EmailOutboxMessage.id)) is None


def test_resend_cooldown_does_not_issue_another_token(
    monkeypatch,
) -> None:
    user = create_user()
    create_token(user)

    response = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": user.email},
    )

    assert response.status_code == 200
    assert response.json()["message"] == auth_api.RESEND_GENERIC_MESSAGE

    with TestingSessionLocal() as db:
        tokens = list(
            db.scalars(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.user_id == user.id
                )
            ).all()
        )
        assert len(tokens) == 1
        assert db.scalar(select(EmailOutboxMessage.id)) is None


def test_resend_hourly_limit_counts_initial_token(
    monkeypatch,
) -> None:
    user = create_user()
    create_token(user)
    age_latest_token(user, age=timedelta(minutes=2))

    original_settings = auth_api.get_settings()
    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: original_settings.model_copy(
            update={
                "email_verification_resend_cooldown_seconds": 1,
                "email_verification_max_resends_per_hour": 1,
            }
        ),
    )

    response = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": user.email},
    )

    assert response.status_code == 200
    assert response.json()["message"] == auth_api.RESEND_GENERIC_MESSAGE

    with TestingSessionLocal() as db:
        tokens = db.scalars(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        ).all()
        assert len(tokens) == 1
        assert db.scalar(select(EmailOutboxMessage.id)) is None


def test_resend_verified_account_returns_generic_response() -> None:
    user = create_user(verified=True)

    response = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": user.email},
    )

    assert response.status_code == 200
    assert response.json()["message"] == auth_api.RESEND_GENERIC_MESSAGE

    with TestingSessionLocal() as db:
        assert db.scalar(select(EmailOutboxMessage.id)) is None


def test_eligible_resend_queues_encrypted_job_and_replaces_token(
    monkeypatch,
) -> None:
    configure_outbox_encryption(monkeypatch)

    user = create_user()
    original_token = create_token(user)
    age_latest_token(user, age=timedelta(minutes=2))

    original_settings = auth_api.get_settings()
    monkeypatch.setattr(
        auth_api,
        "get_settings",
        lambda: original_settings.model_copy(
            update={
                "email_verification_resend_cooldown_seconds": 1,
                "email_verification_max_resends_per_hour": 5,
            }
        ),
    )

    response = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": user.email},
    )

    assert response.status_code == 200
    assert response.json()["message"] == auth_api.RESEND_GENERIC_MESSAGE

    with TestingSessionLocal() as db:
        tokens = list(
            db.scalars(
                select(EmailVerificationToken)
                .where(EmailVerificationToken.user_id == user.id)
                .order_by(EmailVerificationToken.created_at.asc())
            ).all()
        )
        assert len(tokens) == 2

        old_record = next(
            record
            for record in tokens
            if record.token_hash == hash_verification_token(original_token)
        )
        new_record = next(
            record
            for record in tokens
            if record.token_hash != hash_verification_token(original_token)
        )

        assert old_record.used_at is not None
        assert new_record.used_at is None

        jobs = list(db.scalars(select(EmailOutboxMessage)).all())
        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == "pending"
        assert user.email not in job.encrypted_payload

        payload = decrypt_email_payload(job.encrypted_payload)
        assert payload["recipient"] == user.email
        assert hash_verification_token(payload["token"]) == new_record.token_hash
        assert payload["token"] != original_token
