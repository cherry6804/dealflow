import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth.login import authenticate_user
from app.auth.password import hash_password
from app.db.base import Base
from app.db.models.user import User


def create_test_session() -> Session:
    """Create an isolated in-memory database session for authentication tests."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    return Session(engine)


def test_authenticate_user_returns_active_user_for_valid_credentials() -> None:
    db = create_test_session()

    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        password_hash=hash_password("StrongPassword!123"),
        is_active=True,
    )

    db.add(user)
    db.commit()

    authenticated_user = authenticate_user(
        db,
        "user@example.com",
        "StrongPassword!123",
    )

    assert authenticated_user is not None
    assert authenticated_user.id == user.id


def test_authenticate_user_normalizes_email() -> None:
    db = create_test_session()

    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        password_hash=hash_password("StrongPassword!123"),
        is_active=True,
    )

    db.add(user)
    db.commit()

    authenticated_user = authenticate_user(
        db,
        "  USER@EXAMPLE.COM  ",
        "StrongPassword!123",
    )

    assert authenticated_user is not None
    assert authenticated_user.id == user.id


def test_authenticate_user_rejects_wrong_password() -> None:
    db = create_test_session()

    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        password_hash=hash_password("StrongPassword!123"),
        is_active=True,
    )

    db.add(user)
    db.commit()

    authenticated_user = authenticate_user(
        db,
        "user@example.com",
        "WrongPassword!123",
    )

    assert authenticated_user is None


def test_authenticate_user_rejects_unknown_email() -> None:
    db = create_test_session()

    authenticated_user = authenticate_user(
        db,
        "unknown@example.com",
        "StrongPassword!123",
    )

    assert authenticated_user is None


def test_authenticate_user_rejects_inactive_user() -> None:
    db = create_test_session()

    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="Test User",
        password_hash=hash_password("StrongPassword!123"),
        is_active=False,
    )

    db.add(user)
    db.commit()

    authenticated_user = authenticate_user(
        db,
        "user@example.com",
        "StrongPassword!123",
    )

    assert authenticated_user is None