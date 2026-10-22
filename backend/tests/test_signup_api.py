
"""Focused integration tests for account signup and workspace provisioning."""

import uuid
from collections.abc import Generator

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
from app.auth.email_verification import hash_verification_token
from app.config import get_settings
from app.db.base import Base
from app.db.models.auth_session import AuthSession
from app.db.models.email_outbox_message import EmailOutboxMessage
from app.db.models.email_verification_token import EmailVerificationToken
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.role import Role
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
    """Give each test a valid key without depending on the local .env."""
    original_settings = get_settings()
    test_settings = original_settings.model_copy(
        update={
            "email_outbox_encryption_key": SecretStr(
                Fernet.generate_key().decode("ascii")
            )
        }
    )
    monkeypatch.setattr(email_outbox, "get_settings", lambda: test_settings)


def seed_owner_role() -> Role:
    with TestingSessionLocal() as db:
        role = Role(
            id=uuid.uuid4(),
            name="DealFlow Owner",
            description="Workspace owner role for tests.",
            is_active=True,
        )
        db.add(role)
        db.commit()
        db.refresh(role)
        return role


def signup_payload(
    *,
    email: str = "owner@example.com",
    organization_name: str = "Example Realty",
) -> dict[str, str]:
    return {
        "email": email,
        "password": "StrongPassword!123",
        "display_name": "Workspace Owner",
        "organization_name": organization_name,
    }


def test_signup_creates_pending_account_and_encrypted_email_job(
    monkeypatch,
) -> None:
    role = seed_owner_role()
    configure_outbox_encryption(monkeypatch)

    response = client.post(
        "/api/v1/auth/signup",
        json=signup_payload(email="  OWNER@EXAMPLE.COM  "),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"
    assert body["user"]["display_name"] == "Workspace Owner"
    assert body["organization"]["name"] == "Example Realty"
    assert body["verification_required"] is True
    assert "password_hash" not in body["user"]
    assert "session" not in body
    assert "token" not in body
    assert "dealflow_session" not in response.cookies
    assert "set-cookie" not in response.headers

    with TestingSessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == "owner@example.com")
        )
        organization = db.scalar(
            select(Organization).where(
                Organization.name == "Example Realty"
            )
        )

        assert user is not None
        assert user.password_hash != "StrongPassword!123"
        assert user.is_email_verified is False
        assert organization is not None

        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organization_id == organization.id,
                Membership.is_active.is_(True),
            )
        )
        assert membership is not None

        assignment = db.scalar(
            select(MembershipRole).where(
                MembershipRole.membership_id == membership.id,
                MembershipRole.role_id == role.id,
            )
        )
        assert assignment is not None

        verification = db.scalar(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
        assert verification is not None
        assert len(verification.token_hash) == 64

        assert db.scalar(
            select(AuthSession).where(AuthSession.user_id == user.id)
        ) is None

        jobs = list(
            db.scalars(select(EmailOutboxMessage)).all()
        )
        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == "pending"
        assert job.attempts == 0

        # Neither the recipient nor the raw token is stored in plaintext.
        assert "owner@example.com" not in job.encrypted_payload
        assert verification.token_hash not in job.encrypted_payload

        decrypted = decrypt_email_payload(job.encrypted_payload)
        assert decrypted["kind"] == "email_verification"
        assert decrypted["recipient"] == "owner@example.com"
        assert hash_verification_token(decrypted["token"]) == (
            verification.token_hash
        )


def test_signup_duplicate_email_is_rejected(monkeypatch) -> None:
    seed_owner_role()
    configure_outbox_encryption(monkeypatch)

    first = client.post(
        "/api/v1/auth/signup",
        json=signup_payload(),
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/auth/signup",
        json=signup_payload(organization_name="Another Workspace"),
    )
    assert second.status_code == 409

    with TestingSessionLocal() as db:
        assert len(list(db.scalars(select(User)).all())) == 1
        assert len(list(db.scalars(select(Organization)).all())) == 1
        assert len(list(db.scalars(select(EmailOutboxMessage)).all())) == 1


def test_signup_requires_owner_role_to_be_seeded() -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json=signup_payload(),
    )

    assert response.status_code == 503

    with TestingSessionLocal() as db:
        assert db.scalar(select(User.id)) is None
        assert db.scalar(select(Organization.id)) is None
        assert db.scalar(select(EmailOutboxMessage.id)) is None


def test_signup_rejects_short_password() -> None:
    seed_owner_role()
    payload = signup_payload()
    payload["password"] = "short"

    response = client.post(
        "/api/v1/auth/signup",
        json=payload,
    )

    assert response.status_code == 422

    with TestingSessionLocal() as db:
        assert db.scalar(select(User.id)) is None
        assert db.scalar(select(EmailOutboxMessage.id)) is None


def test_signup_rolls_back_everything_when_enqueue_fails(
    monkeypatch,
) -> None:
    seed_owner_role()
    configure_outbox_encryption(monkeypatch)

    def fail_enqueue(*args, **kwargs):
        raise RuntimeError("Simulated outbox enqueue failure.")

    monkeypatch.setattr(
        auth_api,
        "enqueue_verification_email",
        fail_enqueue,
    )

    with TestClient(
        api_test_app,
        raise_server_exceptions=False,
    ) as test_client:
        response = test_client.post(
            "/api/v1/auth/signup",
            json=signup_payload(),
        )

    assert response.status_code == 500

    with TestingSessionLocal() as db:
        assert db.scalar(select(User.id)) is None
        assert db.scalar(select(Organization.id)) is None
        assert db.scalar(select(Membership.id)) is None
        assert db.scalar(select(MembershipRole.id)) is None
        assert db.scalar(select(AuthSession.id)) is None
        assert db.scalar(select(EmailVerificationToken.id)) is None
        assert db.scalar(select(EmailOutboxMessage.id)) is None


def test_verification_token_hash_helper_is_deterministic() -> None:
    token = "test-verification-token"

    assert hash_verification_token(token) == hash_verification_token(token)
    assert hash_verification_token(token) != token
