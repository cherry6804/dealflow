
"""Tests for DealFlow organization discovery."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.organizations import router as organizations_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session

TestingSessionLocal = SessionLocal


def create_user(db: Session) -> User:
    user = User(
        email=f"org-test-{uuid4()}@example.com",
        display_name="Organization Test User",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(
    db: Session,
    *,
    name: str,
    is_active: bool = True,
) -> Organization:
    organization = Organization(
        name=name,
        is_active=is_active,
    )
    db.add(organization)
    db.flush()
    return organization


def create_membership(
    db: Session,
    *,
    user: User,
    organization: Organization,
    is_active: bool = True,
) -> Membership:
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=is_active,
    )
    db.add(membership)
    db.flush()
    return membership


def create_test_app(user: User | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(organizations_router)

    def override_get_db_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session

    if user is not None:
        app.dependency_overrides[get_current_user_context] = (
            lambda: CurrentUserContext(user=user)
        )

    return app


def test_lists_only_active_memberships_and_organizations() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        active_org = create_organization(
            db,
            name="Active Workspace",
        )
        inactive_membership_org = create_organization(
            db,
            name="Inactive Membership Workspace",
        )
        inactive_org = create_organization(
            db,
            name="Inactive Workspace",
            is_active=False,
        )
        unrelated_org = create_organization(
            db,
            name="Unrelated Workspace",
        )

        create_membership(
            db,
            user=user,
            organization=active_org,
        )
        create_membership(
            db,
            user=user,
            organization=inactive_membership_org,
            is_active=False,
        )
        create_membership(
            db,
            user=user,
            organization=inactive_org,
        )

        other_user = create_user(db)
        create_membership(
            db,
            user=other_user,
            organization=unrelated_org,
        )

        db.commit()
        user_id = user.id
        active_org_id = active_org.id

        with TestClient(create_test_app(user=user)) as client:
            response = client.get("/api/v1/organizations")

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": str(active_org_id),
                "name": "Active Workspace",
            }
        ]

        # Confirm the fixtures belong to the intended separate users.
        assert db.scalar(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == unrelated_org.id,
            )
        ) is None


def test_returns_empty_list_when_user_has_no_memberships() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        db.commit()

        with TestClient(create_test_app(user=user)) as client:
            response = client.get("/api/v1/organizations")

        assert response.status_code == 200
        assert response.json() == []


def test_rejects_unauthenticated_requests() -> None:
    with TestClient(create_test_app()) as client:
        response = client.get("/api/v1/organizations")

    assert response.status_code == 401
