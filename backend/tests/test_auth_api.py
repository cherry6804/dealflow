import uuid
from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import router as auth_router
from app.auth.password import hash_password
from app.auth.session import hash_session_token
from app.db.base import Base
from app.db.models.auth_session import AuthSession
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
            id=uuid.uuid4(),
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


def test_login_returns_authenticated_user_and_sets_session_cookie() -> None:
    user = create_user()

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "StrongPassword!123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
        }
    }

    set_cookie = response.headers["set-cookie"]

    assert "dealflow_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie


def test_login_creates_server_side_session_with_hashed_token() -> None:
    user = create_user()

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "StrongPassword!123",
        },
    )

    assert response.status_code == 200

    cookie = response.cookies.get("dealflow_session")

    assert cookie is not None
    assert len(cookie) > 20

    session = TestingSessionLocal()
    try:
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.user_id == user.id,
            )
        )

        assert auth_session is not None
        assert auth_session.token_hash != cookie
        assert len(auth_session.token_hash) == 64
        assert auth_session.revoked_at is None
    finally:
        session.close()


def test_login_rejects_invalid_password() -> None:
    create_user()

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "WrongPassword!123",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Invalid email or password.",
        }
    }

    assert "dealflow_session" not in response.cookies


def test_login_rejects_unknown_email() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "unknown@example.com",
            "password": "StrongPassword!123",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Invalid email or password.",
        }
    }

    assert "dealflow_session" not in response.cookies


def test_login_rejects_inactive_user() -> None:
    create_user(is_active=False)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "StrongPassword!123",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Invalid email or password.",
        }
    }

    assert "dealflow_session" not in response.cookies


def test_login_normalizes_email() -> None:
    user = create_user()

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "  USER@EXAMPLE.COM  ",
            "password": "StrongPassword!123",
        },
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(user.id)


def test_logout_revokes_current_session_and_clears_cookie() -> None:
    user = create_user()

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "StrongPassword!123",
        },
    )

    assert login_response.status_code == 200

    token = client.cookies.get("dealflow_session")
    assert token is not None

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""

    session = TestingSessionLocal()
    try:
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_session_token(token),
            )
        )

        assert auth_session is not None
        assert auth_session.revoked_at is not None
    finally:
        session.close()

    me_response = client.get("/api/v1/auth/me")

    assert me_response.status_code == 401
    assert me_response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Authentication required.",
        }
    }


def test_logout_without_authentication_is_safe() -> None:
    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""


def test_logout_with_invalid_session_is_safe() -> None:
    client.cookies.set(
        "dealflow_session",
        "invalid-session-token",
    )

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert response.content == b""


def test_logout_is_idempotent_for_already_revoked_session() -> None:
    user = create_user()

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "StrongPassword!123",
        },
    )

    assert login_response.status_code == 200

    first_logout = client.post("/api/v1/auth/logout")

    assert first_logout.status_code == 204

    second_logout = client.post("/api/v1/auth/logout")

    assert second_logout.status_code == 204
    assert second_logout.content == b""