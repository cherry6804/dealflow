import uuid
from datetime import datetime, timedelta, timezone

from app.auth.service import (
    create_session,
    get_active_session,
    revoke_session,
)
from app.auth.password import hash_password
from app.db.models.user import User
from app.db.session import SessionLocal


def create_test_user() -> User:
    """Create a user for authentication session tests."""
    return User(
        email=f"session-{uuid.uuid4()}@example.com",
        display_name="Session User",
        password_hash=hash_password("TestPassword!123"),
    )


def test_create_session_persists_session_and_returns_token() -> None:
    with SessionLocal() as db:
        user = create_test_user()
        db.add(user)
        db.commit()
        db.refresh(user)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=12)

        session, token = create_session(
            db,
            user,
            expires_at,
        )

        assert session.id is not None
        assert session.user_id == user.id
        assert session.token_hash
        assert session.token_hash != token
        assert session.revoked_at is None
        assert token


def test_active_session_can_be_retrieved() -> None:
    with SessionLocal() as db:
        user = create_test_user()
        db.add(user)
        db.commit()
        db.refresh(user)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=12)

        _, token = create_session(
            db,
            user,
            expires_at,
        )

        session = get_active_session(db, token)

        assert session is not None
        assert session.user_id == user.id


def test_invalid_session_token_returns_none() -> None:
    with SessionLocal() as db:
        session = get_active_session(
            db,
            "invalid-session-token",
        )

        assert session is None


def test_expired_session_returns_none() -> None:
    with SessionLocal() as db:
        user = create_test_user()
        db.add(user)
        db.commit()
        db.refresh(user)

        expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        _, token = create_session(
            db,
            user,
            expires_at,
        )

        session = get_active_session(db, token)

        assert session is None


def test_revoke_session_invalidates_active_session() -> None:
    with SessionLocal() as db:
        user = create_test_user()
        db.add(user)
        db.commit()
        db.refresh(user)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=12)

        _, token = create_session(
            db,
            user,
            expires_at,
        )

        assert get_active_session(db, token) is not None

        revoked = revoke_session(db, token)

        assert revoked is True
        assert get_active_session(db, token) is None


def test_revoke_unknown_session_returns_false() -> None:
    with SessionLocal() as db:
        assert revoke_session(
            db,
            "unknown-session-token",
        ) is False

def test_revoke_expired_session_records_revocation() -> None:
    with SessionLocal() as db:
        user = create_test_user()
        db.add(user)
        db.commit()
        db.refresh(user)

        expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        session, token = create_session(
            db,
            user,
            expires_at,
        )

        revoked = revoke_session(db, token)

        assert revoked is True

        db.refresh(session)

        assert session.revoked_at is not None