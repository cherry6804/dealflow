
"""Tests for DealFlow site-visit scheduling API routes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.site_visits import router as site_visits_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.property import Property
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.site_visit import SiteVisit
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session


TestingSessionLocal = SessionLocal


def create_user(db: Session) -> User:
    """Create a unique active test user."""
    user = User(
        email=f"site-visit-{uuid4()}@example.com",
        display_name=f"Site Visit User {uuid4()}",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(db: Session) -> Organization:
    """Create a unique active organization."""
    organization = Organization(
        name=f"Site Visit Organization {uuid4()}",
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
    """Grant a permission to a membership through a role."""
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
        name=f"Site Visit Role {uuid4()}",
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
    permission_keys: tuple[str, ...] = ("leads.update",),
) -> tuple[User, Organization]:
    """Create a user with the requested organization permissions."""
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


def create_property(
    db: Session,
    *,
    organization: Organization,
) -> Property:
    """Create a property owned by the supplied organization."""
    property_record = Property(
        organization_id=organization.id,
        city="Chennai",
        state="Tamil Nadu",
        property_type="APARTMENT",
    )
    db.add(property_record)
    db.commit()
    db.refresh(property_record)
    return property_record


def create_lead(
    db: Session,
    *,
    organization: Organization,
) -> Lead:
    """Create a lead and its required contact."""
    contact = Contact(
        organization_id=organization.id,
        first_name="Site Visit",
        last_name="Test Customer",
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
    app.include_router(site_visits_router)

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
    """Create a test client for site-visit API calls."""
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


def valid_payload(
    *,
    property_id: UUID,
    lead_id: UUID,
) -> dict[str, object]:
    """Return a valid site-visit scheduling payload."""
    return {
        "property_id": str(property_id),
        "lead_id": str(lead_id),
        "scheduled_at": (
            datetime.now(timezone.utc) + timedelta(days=2)
        ).isoformat(),
        "ends_at": (
            datetime.now(timezone.utc) + timedelta(days=2, hours=1)
        ).isoformat(),
        "notes": "Discuss property requirements with the customer.",
    }


def test_schedule_site_visit_successfully() -> None:
    """Schedule and persist a visit in the selected organization."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)
        payload = valid_payload(
            property_id=property_record.id,
            lead_id=lead.id,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 201, response.text
        result = response.json()

        assert result["organization_id"] == str(organization.id)
        assert result["property_id"] == str(property_record.id)
        assert result["lead_id"] == str(lead.id)
        assert result["customer_profile_id"] is None
        assert result["owner_user_id"] == str(user.id)
        assert result["status"] == SiteVisit.STATUS_SCHEDULED
        assert result["outcome"] is None
        assert result["notes"] == payload["notes"]
        assert result["created_at"]
        assert result["updated_at"]

        persisted = db.scalar(
            select(SiteVisit).where(
                SiteVisit.id == UUID(result["id"])
            )
        )
        assert persisted is not None
        assert persisted.organization_id == organization.id
        assert persisted.property_id == property_record.id
        assert persisted.lead_id == lead.id
        assert persisted.owner_user_id == user.id
        assert persisted.status == SiteVisit.STATUS_SCHEDULED


def test_schedule_site_visit_requires_customer_reference() -> None:
    """Reject a scheduling request without a lead or customer profile."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        property_record = create_property(
            db,
            organization=organization,
        )
        payload = {
            "property_id": str(property_record.id),
            "scheduled_at": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat(),
        }

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 422


def test_schedule_site_visit_requires_property_id() -> None:
    """Reject a request missing the required property identifier."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)

        payload = {
            "lead_id": str(lead.id),
            "scheduled_at": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat(),
        }

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 422


def test_schedule_site_visit_rejects_timezone_naive_datetime() -> None:
    """Require timezone information on scheduled visit times."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)

        payload = valid_payload(
            property_id=property_record.id,
            lead_id=lead.id,
        )
        payload["scheduled_at"] = "2030-01-15T10:00:00"

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 422


def test_schedule_site_visit_rejects_invalid_time_range() -> None:
    """Reject an end time that is not later than the start time."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)

        payload = valid_payload(
            property_id=property_record.id,
            lead_id=lead.id,
        )
        payload["scheduled_at"] = "2030-01-15T12:00:00+00:00"
        payload["ends_at"] = "2030-01-15T11:00:00+00:00"

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 422


def test_schedule_site_visit_rejects_unknown_property() -> None:
    """Return not found for a property absent from the organization."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        lead = create_lead(db, organization=organization)

        payload = valid_payload(
            property_id=uuid4(),
            lead_id=lead.id,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 404


def test_schedule_site_visit_rejects_cross_tenant_property() -> None:
    """Prevent scheduling against another organization's property."""
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(db)
        organization_b = create_organization(db)
        property_b = create_property(
            db,
            organization=organization_b,
        )
        lead_a = create_lead(db, organization=organization_a)

        payload = valid_payload(
            property_id=property_b.id,
            lead_id=lead_a.id,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 404

        persisted = db.scalars(
            select(SiteVisit).where(
                SiteVisit.organization_id == organization_a.id,
            )
        ).all()
        assert persisted == []


def test_schedule_site_visit_rejects_cross_tenant_lead() -> None:
    """Prevent scheduling against another organization's lead."""
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(db)
        organization_b = create_organization(db)
        property_a = create_property(
            db,
            organization=organization_a,
        )
        lead_b = create_lead(db, organization=organization_b)

        payload = valid_payload(
            property_id=property_a.id,
            lead_id=lead_b.id,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 404


def test_schedule_site_visit_rejects_invalid_owner() -> None:
    """Reject an owner without active membership in the organization."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)

        payload = valid_payload(
            property_id=property_record.id,
            lead_id=lead.id,
        )
        payload["owner_user_id"] = str(uuid4())

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 422
        assert (
            response.json()["detail"]
            == "Site visit owner must be an active member of this organization."
        )


def test_schedule_site_visit_rejects_inactive_owner() -> None:
    """Reject an owner whose membership is inactive."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        inactive_user = create_user(db)
        create_membership(
            db,
            user=inactive_user,
            organization=organization,
            is_active=False,
        )
        db.commit()

        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)

        payload = valid_payload(
            property_id=property_record.id,
            lead_id=lead.id,
        )
        payload["owner_user_id"] = str(inactive_user.id)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 422


def test_schedule_site_visit_requires_permission() -> None:
    """Reject scheduling without leads.update permission."""
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)
        create_membership(
            db,
            user=user,
            organization=organization,
        )
        db.commit()

        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)
        payload = valid_payload(
            property_id=property_record.id,
            lead_id=lead.id,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Permission denied."


def test_schedule_site_visit_requires_tenant_context() -> None:
    """Reject scheduling when no organization is selected."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        property_record = create_property(
            db,
            organization=organization,
        )
        lead = create_lead(db, organization=organization)
        payload = valid_payload(
            property_id=property_record.id,
            lead_id=lead.id,
        )

        with make_test_client(user=user) as client:
            response = client.post(
                "/api/v1/site-visits",
                json=payload,
            )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Organization context is required."
        )
