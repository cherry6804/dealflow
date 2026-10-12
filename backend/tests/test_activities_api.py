"""Tests for DealFlow lead activity API routes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator
from uuid import UUID, uuid4
from app.activities.schemas import ActivityCreateRequest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.service import create_activity
from app.api.activities import router as activities_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
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
from app.tenant.dependencies import get_tenant_context


TestingSessionLocal = SessionLocal


def create_user(db: Session) -> User:
    user = User(
        email=f"activity-api-{uuid4()}@example.com",
        display_name=f"Activity API User {uuid4()}",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(db: Session) -> Organization:
    organization = Organization(
        name=f"Activity API Organization {uuid4()}",
        is_active=True,
    )
    db.add(organization)
    db.flush()
    return organization


def create_membership(
    db: Session,
    *,
    user: User,
    organization: Organization,
) -> Membership:
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=True,
    )
    db.add(membership)
    db.flush()
    return membership


def grant_permission(
    db: Session,
    *,
    membership: Membership,
    permission_key: str,
) -> None:
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
        name=f"Activity API Role {uuid4()}",
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
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(
        db,
        user=user,
        organization=organization,
    )

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
    contact = Contact(
        organization_id=organization.id,
        first_name="Activity",
        last_name="API Test",
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
    app = FastAPI()
    app.include_router(activities_router)

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


@contextmanager
def make_test_client(*, user: User) -> Iterator[TestClient]:
    app = create_test_app(user=user)
    with TestClient(app) as client:
        yield client


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    client.headers.update(
        {"X-Organization-ID": str(organization.id)}
    )


def test_create_activity_successfully() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/leads/{lead.id}/activities",
                json={
                    "activity_type": "NOTE",
                    "title": "Customer discussion",
                    "description": "Discussed requirements",
                    "details": {"source": "phone"},
                },
            )

        assert response.status_code == 201
        payload = response.json()
        assert payload["organization_id"] == str(organization.id)
        assert payload["lead_id"] == str(lead.id)
        assert payload["actor_id"] == str(user.id)
        assert payload["activity_type"] == "NOTE"
        assert payload["title"] == "Customer discussion"

        persisted = db.scalar(
            select(Activity).where(
                Activity.id == UUID(payload["id"])
            )
        )
        assert persisted is not None
        assert persisted.organization_id == organization.id


def test_create_activity_rejects_cross_tenant_lead() -> None:
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        organization_b = create_organization(db)
        lead_b = create_lead(db, organization=organization_b)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.post(
                f"/api/v1/leads/{lead_b.id}/activities",
                json={
                    "activity_type": "NOTE",
                    "title": "Cross-tenant attempt",
                },
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Lead not found."

        activities = db.scalars(
            select(Activity).where(
                Activity.organization_id == organization_a.id,
                Activity.lead_id == lead_b.id,
            )
        ).all()
        assert activities == []


def test_create_activity_requires_permission() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)
        create_membership(
            db,
            user=user,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                f"/api/v1/leads/{lead.id}/activities",
                json={
                    "activity_type": "NOTE",
                    "title": "Unauthorized attempt",
                },
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Permission denied."


def test_list_activities_successfully_in_timeline_order() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        lead = create_lead(db, organization=organization)

        base_time = datetime.now(timezone.utc)
        for title, occurred_at in (
            ("Later activity", base_time + timedelta(minutes=10)),
            ("Earlier activity", base_time),
        ):
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

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"/api/v1/leads/{lead.id}/activities"
            )

        assert response.status_code == 200
        payload = response.json()
        assert [
            item["title"] for item in payload["items"]
        ] == ["Earlier activity", "Later activity"]


def test_list_activities_returns_404_for_missing_lead() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"/api/v1/leads/{uuid4()}/activities"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Lead not found."


def test_list_activities_rejects_cross_tenant_lead() -> None:
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        organization_b = create_organization(db)
        lead_b = create_lead(db, organization=organization_b)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)
            response = client.get(
                f"/api/v1/leads/{lead_b.id}/activities"
            )

        assert response.status_code == 404


def test_list_activities_requires_permission() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)
        create_membership(
            db,
            user=user,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"/api/v1/leads/{lead.id}/activities"
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Permission denied."


def test_create_activity_rejects_invalid_activity_type() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/leads/{lead.id}/activities",
                json={
                    "activity_type": "NOT_A_TYPE",
                    "title": "Invalid type",
                },
            )

        assert response.status_code == 422
