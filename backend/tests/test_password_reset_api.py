
"""Integration tests for password-reset API endpoints."""

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import router as auth_router
from app.auth.password import hash_password, verify_password
from app.auth.password_reset import create_password_reset_token
from app.auth.session import hash_session_token
from app.db.base import Base
from app.db.models.auth_session import AuthSession
from app.db.models.password_reset_token import PasswordResetToken
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
    """Provide an isolated database session for API tests."""
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
    """Create clean database tables for each test."""
    Base.metadata.create_all(engine)
    client.cookies.clear()


def teardown_function() -> None:
    """Remove database tables after each test."""
    Base.metadata.drop_all(engine)


def teardown_module() -> None:
    """Remove dependency overrides after the module finishes."""
    api_test_app.dependency_overrides.clear()


def create_user(
    email: str = "reset@example.com",
    password: str = "StrongPassword!123",
    is_active: bool = True,
) -> User:
    """Create a test user."""
    session = TestingSessionLocal()
    try:
        user = User(
            id=uuid.uuid4(),
            email=email,
            display_name="Password Reset User",
            password_hash=hash_password(password),
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def issue_reset_token(user_id: uuid.UUID) -> str:
    """Create a reset token using the production token service."""
    session = TestingSessionLocal()
    try:
        _, raw_token = create_password_reset_token(session, user_id)
        session.commit()
        return raw_token
    finally:
        session.close()


def get_user(user_id: uuid.UUID) -> User:
    """Read a user from the test database."""
    session = TestingSessionLocal()
    try:
        user = session.get(User, user_id)
        assert user is not None
        session.expunge(user)
        return user
    finally:
        session.close()


def test_reset_request_returns_generic_message_for_existing_user() -> None:
    create_user()

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )

    assert response.status_code == 200
    assert "password-reset email" in response.json()["message"].lower()

    session = TestingSessionLocal()
    try:
        token = session.scalar(select(PasswordResetToken))
        assert token is not None
        assert token.token_hash != ""
        assert len(token.token_hash) == 64
    finally:
        session.close()


def test_reset_request_returns_same_message_for_unknown_user() -> None:
    create_user()

    existing_response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    unknown_response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )

    assert existing_response.status_code == 200
    assert unknown_response.status_code == 200
    assert (
        existing_response.json()["message"]
        == unknown_response.json()["message"]
    )


def test_reset_request_normalizes_email() -> None:
    user = create_user(email="reset@example.com")

    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "  RESET@EXAMPLE.COM  "},
    )

    assert response.status_code == 200

    session = TestingSessionLocal()
    try:
        token = session.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id
            )
        )
        assert token is not None
    finally:
        session.close()


def test_reset_request_rejects_invalid_email_format() -> None:
    response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 422


def test_reset_request_throttles_repeated_requests() -> None:
    create_user()

    first_response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    second_response = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert (
        first_response.json()["message"]
        == second_response.json()["message"]
    )

    session = TestingSessionLocal()
    try:
        tokens = session.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == get_user_id("reset@example.com")
            )
        ).all()
        assert len(tokens) == 1
    finally:
        session.close()


def get_user_id(email: str) -> uuid.UUID:
    """Return a test user's identifier."""
    session = TestingSessionLocal()
    try:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        return user.id
    finally:
        session.close()


def test_reset_confirm_changes_password() -> None:
    user = create_user()
    token = issue_reset_token(user.id)

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": token,
            "new_password": "NewStrongPassword!456",
        },
    )

    assert response.status_code == 200

    updated_user = get_user(user.id)
    assert verify_password(
        "NewStrongPassword!456",
        updated_user.password_hash,
    )
    assert not verify_password(
        "StrongPassword!123",
        updated_user.password_hash,
    )


def test_reset_confirm_rejects_invalid_token_without_changing_password() -> None:
    user = create_user()
    original_hash = get_user(user.id).password_hash

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": "invalid-reset-token",
            "new_password": "NewStrongPassword!456",
        },
    )

    assert response.status_code == 400
    assert get_user(user.id).password_hash == original_hash


def test_reset_confirm_rejects_expired_token() -> None:
    user = create_user()

    session = TestingSessionLocal()
    try:
        _, token = create_password_reset_token(session, user.id)
        record = session.scalar(select(PasswordResetToken))
        assert record is not None
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
    finally:
        session.close()

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": token,
            "new_password": "NewStrongPassword!456",
        },
    )

    assert response.status_code == 400


def test_reset_confirm_rejects_reused_token() -> None:
    user = create_user()
    token = issue_reset_token(user.id)

    payload = {
        "token": token,
        "new_password": "NewStrongPassword!456",
    }

    first_response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json=payload,
    )
    second_response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 400


def test_reset_confirm_revokes_existing_sessions() -> None:
    user = create_user()

    session = TestingSessionLocal()
    try:
        active_session = AuthSession(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_session_token("existing-session-token"),
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        session.add(active_session)
        session.commit()
    finally:
        session.close()

    token = issue_reset_token(user.id)

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": token,
            "new_password": "NewStrongPassword!456",
        },
    )

    assert response.status_code == 200

    session = TestingSessionLocal()
    try:
        updated_session = session.scalar(
            select(AuthSession).where(
                AuthSession.user_id == user.id,
            )
        )
        assert updated_session is not None
        assert updated_session.revoked_at is not None
    finally:
        session.close()


def test_reset_confirm_invalidates_other_outstanding_tokens() -> None:
    user = create_user()
    first_token = issue_reset_token(user.id)
    second_token = issue_reset_token(user.id)

    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": first_token,
            "new_password": "NewStrongPassword!456",
        },
    )

    assert response.status_code == 200

    second_response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": second_token,
            "new_password": "AnotherStrongPassword!789",
        },
    )

    assert second_response.status_code == 400
