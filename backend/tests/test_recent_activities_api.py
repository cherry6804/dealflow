
"""Tests for the cross-lead recent activity feed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.schemas import ActivityCreateRequest
from app.activities.service import create_activity
from app.api.leads import router as leads_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.activity import Activity
from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session


TestingSessionLocal = SessionLocal


def create_user(db: Session) -> User:
    """Create a unique active test user."""
    user = User(
        email=f"recent-activity-{uuid4()}@example.com",
        display_name=f"Recent Activity User {uuid4()}",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(db: Session) -> Organization:
    """Create a unique active test organization."""
    organization = Organization(
        name=f"Recent Activity Organization {uuid4()}",
        is_active=True,
    )
    db.add(organization)
    db.flush()
    return organization


def grant_permission(
    db: Session,
    *,
    membership: Membership,
    permission_key: str,
) -> None:
    """Grant one permission to a membership using a dedicated role."""
    permission = db.scalar(
        select(Permission).where(Permission.key == permission_key)
    )

    if permission is None:
        permission = Permission(
            key=permission_key,
            is_active=True,
        )
        db.add(permission)
        db.flush()
    elif not permission.is_active:
        permission.is_active = True
        db.flush()

    role = Role(
        name=f"Recent Activity Role {uuid4()}",
        organization_id=membership.organization_id,
        is_active=True,
    )
    db.add(role)
    db.flush()

    db.add(
        MembershipRole(
            membership_id=membership.id,
            role_id=role.id,
        )
    )
    db.add(
        RolePermission(
            role_id=role.id,
            permission_id=permission.id,
        )
    )
    db.flush()


def create_authorized_user(
    db: Session,
    *,
    permission_keys: tuple[str, ...],
) -> tuple[User, Organization]:
    """Create a user with permissions in a new organization."""
    user = create_user(db)
    organization = create_organization(db)

    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=True,
    )
    db.add(membership)
    db.flush()

    for permission_key in permission_keys:
        grant_permission(
            db,
            membership=membership,
            permission_key=permission_key,
        )

    db.commit()
    return user, organization


def create_lead(
    db: Session,
    *,
    organization: Organization,
) -> Lead:
    """Create a lead owned by the specified organization."""
    contact = Contact(
        organization_id=organization.id,
        first_name="Recent",
        last_name="Activity Test",
        is_active=True,
    )
    db.add(contact)
    db.flush()

    lead = Lead(
        organization_id=organization.id,
        contact_id=contact.id,
        status=Lead.STATUS_NEW,
        is_active=True,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def create_test_app(*, user: User) -> FastAPI:
    """Create a test app with injected authentication and database."""
    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )
    return app


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    """Select the organization for an API request."""
    client.headers.update(
        {"X-Organization-ID": str(organization.id)}
    )


def add_activity(
    db: Session,
    *,
    organization: Organization,
    user: User,
    lead: Lead,
    title: str,
    occurred_at: datetime,
) -> Activity:
    """Create an activity with a controlled timestamp."""
    activity = create_activity(
        db,
        organization_id=organization.id,
        actor_id=user.id,
        lead_id=lead.id,
        payload=ActivityCreateRequest(
            activity_type="NOTE",
            title=title,
            occurred_at=occurred_at,
        ),
    )
    assert activity is not None
    db.flush()
    return activity


def test_recent_activities_are_newest_first_across_leads() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        lead_one = create_lead(db, organization=organization)
        lead_two = create_lead(db, organization=organization)
        base_time = datetime.now(timezone.utc)

        add_activity(
            db,
            organization=organization,
            user=user,
            lead=lead_one,
            title="Old activity",
            occurred_at=base_time - timedelta(minutes=10),
        )
        add_activity(
            db,
            organization=organization,
            user=user,
            lead=lead_two,
            title="Newest activity",
            occurred_at=base_time,
        )
        add_activity(
            db,
            organization=organization,
            user=user,
            lead=lead_one,
            title="Middle activity",
            occurred_at=base_time - timedelta(minutes=5),
        )
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            add_tenant_header(client, organization)
            response = client.get("/api/v1/leads/activities/recent")

        assert response.status_code == 200, response.text
        items = response.json()["items"]

        assert [item["title"] for item in items] == [
            "Newest activity",
            "Middle activity",
            "Old activity",
        ]
        assert all(
            item["actor_display_name"] == user.display_name
            for item in items
        )
        assert items[0]["lead_id"] == str(lead_two.id)


def test_recent_activities_respect_limit() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        lead = create_lead(db, organization=organization)
        base_time = datetime.now(timezone.utc)

        for index in range(5):
            add_activity(
                db,
                organization=organization,
                user=user,
                lead=lead,
                title=f"Activity {index}",
                occurred_at=base_time + timedelta(minutes=index),
            )
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            add_tenant_header(client, organization)
            response = client.get(
                "/api/v1/leads/activities/recent?limit=2"
            )

        assert response.status_code == 200, response.text
        items = response.json()["items"]

        assert len(items) == 2
        assert [item["title"] for item in items] == [
            "Activity 4",
            "Activity 3",
        ]


def test_recent_activities_do_not_expose_other_tenants() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )

        lead_a = create_lead(db, organization=organization_a)
        lead_b = create_lead(db, organization=organization_b)
        base_time = datetime.now(timezone.utc)

        add_activity(
            db,
            organization=organization_a,
            user=user_a,
            lead=lead_a,
            title="Visible tenant activity",
            occurred_at=base_time,
        )
        add_activity(
            db,
            organization=organization_b,
            user=user_b,
            lead=lead_b,
            title="Hidden tenant activity",
            occurred_at=base_time + timedelta(minutes=1),
        )
        db.commit()

        app = create_test_app(user=user_a)
        with TestClient(app) as client:
            add_tenant_header(client, organization_a)
            response = client.get("/api/v1/leads/activities/recent")

        assert response.status_code == 200, response.text
        items = response.json()["items"]

        assert [item["title"] for item in items] == [
            "Visible tenant activity"
        ]
        assert all(
            item["organization_id"] == str(organization_a.id)
            for item in items
        )

def test_recent_activities_require_read_permission() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)
        db.add(
            Membership(
                user_id=user.id,
                organization_id=organization.id,
                is_active=True,
            )
        )
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            add_tenant_header(client, organization)
            response = client.get("/api/v1/leads/activities/recent")

        assert response.status_code == 403
        assert response.json()["detail"] == "Permission denied."


def test_recent_activities_reject_invalid_limit() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )

        app = create_test_app(user=user)
        with TestClient(app) as client:
            add_tenant_header(client, organization)
            response = client.get(
                "/api/v1/leads/activities/recent?limit=0"
            )

        assert response.status_code == 422
