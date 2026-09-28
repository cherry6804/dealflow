from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import router as auth_router
from app.auth.password import hash_password
from app.auth.service import create_session
from app.config import get_settings
from app.db.base import Base
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
    """Provide a database session for API integration tests."""
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
    """Create a clean database before each test."""
    Base.metadata.create_all(engine)


def teardown_function() -> None:
    """Remove all test tables after each test."""
    Base.metadata.drop_all(engine)


def teardown_module() -> None:
    """Clear dependency overrides after the module finishes."""
    api_test_app.dependency_overrides.clear()


def create_user(
    email: str = "user@example.com",
    password: str = "StrongPassword!123",
    display_name: str = "Test User",
    is_active: bool = True,
) -> User:
    """Create a test user."""
    session = TestingSessionLocal()

    try:
        user = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def create_session_for_user(user: User) -> str:
    """Create an authenticated session for a test user."""
    session = TestingSessionLocal()

    try:
        settings = get_settings()
        expires_at = datetime.now(timezone.utc) + timedelta(
            hours=settings.auth_session_lifetime_hours
        )

        _, token = create_session(
            db=session,
            user=user,
            expires_at=expires_at,
        )

        return token
    finally:
        session.close()


def test_me_returns_authenticated_user() -> None:
    user = create_user()
    token = create_session_for_user(user)

    settings = get_settings()

    client.cookies.set(
        settings.auth_cookie_name,
        token,
    )

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
        }
    }


def test_me_rejects_missing_authentication() -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Authentication required.",
        }
    }


def test_me_rejects_invalid_session() -> None:
    settings = get_settings()

    client.cookies.set(
        settings.auth_cookie_name,
        "invalid-session-token",
    )

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Authentication required.",
        }
    }


def test_me_rejects_inactive_user() -> None:
    user = create_user(is_active=False)
    token = create_session_for_user(user)

    settings = get_settings()

    client.cookies.set(
        settings.auth_cookie_name,
        token,
    )

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Authentication required.",
        }
    }