
"""Focused integration tests for account signup and workspace provisioning."""

import uuid
from collections.abc import Generator

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.api import auth as auth_api
from app.api.auth import router as auth_router
from app.auth.session import hash_session_token
from app.db.base import Base
from app.db.models.auth_session import AuthSession
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


def test_signup_creates_user_workspace_membership_role_and_session() -> None:
    role = seed_owner_role()

    response = client.post(
        "/api/v1/auth/signup",
        json=signup_payload(email="  OWNER@EXAMPLE.COM  "),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"
    assert body["user"]["display_name"] == "Workspace Owner"
    assert body["organization"]["name"] == "Example Realty"
    assert "password_hash" not in body["user"]
    assert "session" not in body
    assert "token" not in body

    cookie = response.cookies.get("dealflow_session")
    assert cookie
    assert "HttpOnly" in response.headers["set-cookie"]

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

        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == hash_session_token(cookie)
            )
        )
        assert session is not None
        assert session.user_id == user.id
        assert session.revoked_at is None


def test_signup_rejects_duplicate_email() -> None:
    seed_owner_role()

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


def test_signup_requires_owner_role_to_be_seeded() -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json=signup_payload(),
    )

    assert response.status_code == 503

    with TestingSessionLocal() as db:
        assert db.scalar(select(User.id)) is None
        assert db.scalar(select(Organization.id)) is None


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


def test_signup_rolls_back_all_records_when_session_creation_fails(
    monkeypatch,
) -> None:
    seed_owner_role()

    original_create_session = auth_api.create_session

    def create_session_then_fail(*args, **kwargs):
        original_create_session(*args, **kwargs)
        raise HTTPException(
            status_code=503,
            detail="Simulated session creation failure.",
        )

    monkeypatch.setattr(
        auth_api,
        "create_session",
        create_session_then_fail,
    )

    response = client.post(
        "/api/v1/auth/signup",
        json=signup_payload(),
    )

    assert response.status_code == 503

    with TestingSessionLocal() as db:
        assert db.scalar(select(User.id)) is None
        assert db.scalar(select(Organization.id)) is None
        assert db.scalar(select(Membership.id)) is None
        assert db.scalar(select(MembershipRole.id)) is None
        assert db.scalar(select(AuthSession.id)) is None
