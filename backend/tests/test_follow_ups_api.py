"""Tests for DealFlow follow-up creation API routes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.follow_ups import router as follow_ups_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.contact import Contact
from app.db.models.follow_up import FollowUp
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
        email=f"follow-up-api-{uuid4()}@example.com",
        display_name=f"Follow-up API User {uuid4()}",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(db: Session) -> Organization:
    """Create a unique active test organization."""
    organization = Organization(
        name=f"Follow-up API Organization {uuid4()}",
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
    is_active: bool = True,
) -> Membership:
    """Create an organization membership."""
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=is_active,
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
    """Grant a permission through a role."""
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
        name=f"Follow-up API Role {uuid4()}",
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
    """Create a user with the specified tenant permissions."""
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
    """Create and persist a lead for an organization."""
    contact = Contact(
        organization_id=organization.id,
        first_name="Follow-up",
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
    """Create a test application with injected authentication."""
    app = FastAPI()
    app.include_router(follow_ups_router)

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
    """Create a test client for follow-up API calls."""
    app = create_test_app(user=user)
    with TestClient(app) as client:
        yield client


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    """Select the organization for an API request."""
    client.headers.update(
        {"X-Organization-ID": str(organization.id)}
    )


def valid_payload() -> dict[str, object]:
    """Return a valid follow-up creation payload."""
    return {
        "follow_up_type": "CALL",
        "title": "Call the customer",
        "description": "Discuss property requirements",
        "due_at": (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat(),
    }


def test_create_follow_up_successfully() -> None:
    """Create a pending follow-up owned by the current user."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/leads/{lead.id}/follow-ups",
                json=valid_payload(),
            )

        assert response.status_code == 201, response.text
        payload = response.json()

        assert payload["organization_id"] == str(organization.id)
        assert payload["lead_id"] == str(lead.id)
        assert payload["owner_user_id"] == str(user.id)
        assert payload["follow_up_type"] == "CALL"
        assert payload["title"] == "Call the customer"
        assert payload["description"] == "Discuss property requirements"
        assert payload["status"] == "PENDING"
        assert payload["completed_at"] is None
        assert payload["completed_by_user_id"] is None

        persisted = db.scalar(
            select(FollowUp).where(
                FollowUp.id == UUID(payload["id"])
            )
        )
        assert persisted is not None
        assert persisted.organization_id == organization.id
        assert persisted.lead_id == lead.id
        assert persisted.owner_user_id == user.id
        assert persisted.status == FollowUp.STATUS_PENDING


def test_create_follow_up_rejects_cross_tenant_lead() -> None:
    """Do not expose or create follow-ups for another tenant's lead."""
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
                f"/api/v1/leads/{lead_b.id}/follow-ups",
                json=valid_payload(),
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Lead not found."

        persisted = db.scalars(
            select(FollowUp).where(
                FollowUp.organization_id == organization_a.id,
                FollowUp.lead_id == lead_b.id,
            )
        ).all()
        assert persisted == []


def test_create_follow_up_requires_permission() -> None:
    """Require leads.update permission to create a follow-up."""
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
                f"/api/v1/leads/{lead.id}/follow-ups",
                json=valid_payload(),
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Permission denied."


def test_create_follow_up_rejects_invalid_owner() -> None:
    """Reject an owner who has no membership in the organization."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)

        payload = valid_payload()
        payload["owner_user_id"] = str(uuid4())

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/leads/{lead.id}/follow-ups",
                json=payload,
            )

        assert response.status_code == 422
        assert (
            response.json()["detail"]
            == "Follow-up owner must be an active member of this organization."
        )


def test_create_follow_up_rejects_inactive_owner() -> None:
    """Reject an owner whose organization membership is inactive."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        inactive_user = create_user(db)
        create_membership(
            db,
            user=inactive_user,
            organization=organization,
            is_active=False,
        )
        db.commit()

        lead = create_lead(db, organization=organization)
        payload = valid_payload()
        payload["owner_user_id"] = str(inactive_user.id)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/leads/{lead.id}/follow-ups",
                json=payload,
            )

        assert response.status_code == 422


def test_create_follow_up_rejects_invalid_request() -> None:
    """Reject unsupported follow-up types and invalid payloads."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)

        payload = valid_payload()
        payload["follow_up_type"] = "NOT_A_TYPE"

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/leads/{lead.id}/follow-ups",
                json=payload,
            )

        assert response.status_code == 422

def create_pending_follow_up(
    db: Session,
    *,
    organization: Organization,
    lead: Lead,
    owner: User,
) -> FollowUp:
    """Create and persist a pending follow-up for API tests."""
    follow_up = FollowUp(
        organization_id=organization.id,
        lead_id=lead.id,
        owner_user_id=owner.id,
        follow_up_type="CALL",
        title="Follow up with customer",
        description="Discuss next steps",
        due_at=datetime.now(timezone.utc) + timedelta(days=2),
        status=FollowUp.STATUS_PENDING,
    )
    db.add(follow_up)
    db.commit()
    db.refresh(follow_up)
    return follow_up


def test_complete_follow_up_successfully() -> None:
    """Record completion status, timestamp, and authenticated user."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)
        follow_up = create_pending_follow_up(
            db,
            organization=organization,
            lead=lead,
            owner=user,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/follow-ups/{follow_up.id}/complete",
                json={},
            )

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "COMPLETED"
        assert result["completed_by_user_id"] == str(user.id)
        assert result["completed_at"] is not None

        db.refresh(follow_up)
        assert follow_up.status == FollowUp.STATUS_COMPLETED
        assert follow_up.completed_by_user_id == user.id
        assert follow_up.completed_at is not None


def test_reschedule_pending_follow_up_successfully() -> None:
    """Update the due date of a pending follow-up."""
    new_due_at = datetime.now(timezone.utc) + timedelta(days=5)

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)
        follow_up = create_pending_follow_up(
            db,
            organization=organization,
            lead=lead,
            owner=user,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.patch(
                f"/api/v1/follow-ups/{follow_up.id}/reschedule",
                json={"due_at": new_due_at.isoformat()},
            )

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "PENDING"
        assert datetime.fromisoformat(result["due_at"]) == new_due_at

        db.refresh(follow_up)
        assert follow_up.due_at == new_due_at


def test_complete_follow_up_rejects_already_completed_follow_up() -> None:
    """Reject a second completion attempt."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)
        follow_up = create_pending_follow_up(
            db,
            organization=organization,
            lead=lead,
            owner=user,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            first_response = client.post(
                f"/api/v1/follow-ups/{follow_up.id}/complete",
                json={},
            )
            assert first_response.status_code == 200

            original_completed_at = first_response.json()["completed_at"]

            second_response = client.post(
                f"/api/v1/follow-ups/{follow_up.id}/complete",
                json={},
            )

        assert second_response.status_code == 409
        db.refresh(follow_up)
        assert follow_up.completed_at is not None
        assert follow_up.completed_at.isoformat() == (
            datetime.fromisoformat(original_completed_at).isoformat()
        )


def test_reschedule_follow_up_rejects_completed_follow_up() -> None:
    """Do not reschedule a completed follow-up."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.update",),
        )
        lead = create_lead(db, organization=organization)
        follow_up = create_pending_follow_up(
            db,
            organization=organization,
            lead=lead,
            owner=user,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            complete_response = client.post(
                f"/api/v1/follow-ups/{follow_up.id}/complete",
                json={},
            )
            assert complete_response.status_code == 200

            response = client.patch(
                f"/api/v1/follow-ups/{follow_up.id}/reschedule",
                json={
                    "due_at": (
                        datetime.now(timezone.utc) + timedelta(days=7)
                    ).isoformat()
                },
            )

        assert response.status_code == 409
