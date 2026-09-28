import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.auth.password import hash_password
from app.auth.service import create_session
from app.config import get_settings
from app.db.base import Base
from app.db.models.auth_session import AuthSession
from app.db.models.user import User
from app.db.session import get_db_session


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
    """Provide a database session for authentication dependency tests."""
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()


test_app = FastAPI()

test_app.dependency_overrides[get_db_session] = override_get_db_session


@test_app.get("/protected")
def protected_endpoint(
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Return the current authenticated user."""
    return {
        "id": str(user.id),
        "email": user.email,
    }


client = TestClient(test_app)


def setup_function() -> None:
    """Create a clean database before each test."""
    Base.metadata.create_all(engine)


def teardown_function() -> None:
    """Remove all test tables after each test."""
    Base.metadata.drop_all(engine)


def create_user(
    is_active: bool = True,
) -> User:
    """Create a test user."""
    session = TestingSessionLocal()

    try:
        user = User(
            id=uuid.uuid4(),
            email="user@example.com",
            display_name="Test User",
            password_hash=hash_password("StrongPassword!123"),
            is_active=is_active,
        )

        session.add(user)
        session.commit()
        session.refresh(user)

        return user
    finally:
        session.close()


def create_session_for_user(
    user: User,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> str:
    """Create a test authentication session and return its raw token."""
    session = TestingSessionLocal()

    try:
        if expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        auth_session, token = create_session(
            db=session,
            user=user,
            expires_at=expires_at,
        )

        if revoked_at is not None:
            auth_session.revoked_at = revoked_at
            session.commit()

        return token
    finally:
        session.close()


def test_get_current_user_accepts_valid_session() -> None:
    user = create_user()
    token = create_session_for_user(user)

    response = client.get(
        "/protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
    }


def test_get_current_user_rejects_missing_cookie() -> None:
    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required.",
    }


def test_get_current_user_rejects_invalid_token() -> None:
    response = client.get(
        "/protected",
        cookies={
            get_settings().auth_cookie_name: "invalid-token",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required.",
    }


def test_get_current_user_rejects_revoked_session() -> None:
    user = create_user()

    token = create_session_for_user(
        user,
        revoked_at=datetime.now(timezone.utc),
    )

    response = client.get(
        "/protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required.",
    }


def test_get_current_user_rejects_expired_session() -> None:
    user = create_user()

    token = create_session_for_user(
        user,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    response = client.get(
        "/protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required.",
    }


def test_get_current_user_rejects_inactive_user() -> None:
    user = create_user(is_active=False)
    token = create_session_for_user(user)

    response = client.get(
        "/protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required.",
    }