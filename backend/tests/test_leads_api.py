"""Tests for DealFlow Lead API routes."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.leads import router as leads_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
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


def create_user(
    db: Session,
    *,
    email: str | None = None,
    is_active: bool = True,
) -> User:
    """Create a unique test user."""
    user = User(
        email=email or f"user-{uuid4()}@example.com",
        display_name=f"Test User {uuid4()}",
        password_hash="test-password-hash",
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(
    db: Session,
    *,
    name: str | None = None,
    is_active: bool = True,
) -> Organization:
    """Create a unique test organization."""
    organization = Organization(
        name=name or f"Test Organization-{uuid4()}",
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
    """Create a membership connecting a user to an organization."""
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=is_active,
    )
    db.add(membership)
    db.flush()
    return membership


def create_role(
    db: Session,
    *,
    name: str | None = None,
    is_active: bool = True,
) -> Role:
    """Create a unique test role."""
    role = Role(
        name=name or f"Test Role-{uuid4()}",
        is_active=is_active,
    )
    db.add(role)
    db.flush()
    return role


def get_or_create_permission(
    db: Session,
    *,
    key: str,
    is_active: bool = True,
) -> Permission:
    """Return an existing permission or create it when absent."""
    permission = db.scalar(
        select(Permission).where(
            Permission.key == key,
        )
    )

    if permission is not None:
        if permission.is_active != is_active:
            permission.is_active = is_active
            db.flush()

        return permission

    permission = Permission(
        key=key,
        is_active=is_active,
    )
    db.add(permission)
    db.flush()

    return permission


def assign_role_to_membership(
    db: Session,
    *,
    membership: Membership,
    role: Role,
) -> MembershipRole:
    """Assign a role to a membership."""
    membership_role = MembershipRole(
        membership_id=membership.id,
        role_id=role.id,
    )
    db.add(membership_role)
    db.flush()
    return membership_role


def assign_permission_to_role(
    db: Session,
    *,
    role: Role,
    permission: Permission,
) -> RolePermission:
    """Assign a permission to a role."""
    role_permission = RolePermission(
        role_id=role.id,
        permission_id=permission.id,
    )
    db.add(role_permission)
    db.flush()
    return role_permission


def grant_permission(
    db: Session,
    *,
    user: User,
    organization: Organization,
    permission_key: str,
) -> None:
    """Grant a globally defined permission to a tenant membership."""
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == organization.id,
        )
    )

    assert membership is not None

    role = create_role(db)

    permission = get_or_create_permission(
        db,
        key=permission_key,
        is_active=True,
    )

    assign_role_to_membership(
        db,
        membership=membership,
        role=role,
    )

    assign_permission_to_role(
        db,
        role=role,
        permission=permission,
    )

    db.flush()


def create_authorized_user(
    db: Session,
    *,
    permission_key: str,
) -> tuple[User, Organization]:
    """Create a user, tenant, membership, role, and permission grant."""
    user = create_user(db)
    organization = create_organization(db)

    membership = create_membership(
        db,
        user=user,
        organization=organization,
    )

    role = create_role(db)

    permission = get_or_create_permission(
        db,
        key=permission_key,
        is_active=True,
    )

    assign_role_to_membership(
        db,
        membership=membership,
        role=role,
    )

    assign_permission_to_role(
        db,
        role=role,
        permission=permission,
    )

    db.commit()

    return user, organization


def create_contact(
    db: Session,
    *,
    organization: Organization,
    first_name: str,
    last_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    is_active: bool = True,
) -> Contact:
    """Create and persist a test Contact."""
    contact = Contact(
        organization_id=organization.id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        is_active=is_active,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def create_lead(
    db: Session,
    *,
    organization: Organization,
    contact: Contact,
    status: str = Lead.STATUS_NEW,
    interest: str | None = None,
    outcome: str | None = None,
    owner_user_id=None,
    next_action: str | None = None,
    next_action_at=None,
    is_active: bool = True,
) -> Lead:
    """Create and persist a test Lead."""
    lead = Lead(
        organization_id=organization.id,
        contact_id=contact.id,
        status=status,
        interest=interest,
        outcome=outcome,
        owner_user_id=owner_user_id,
        next_action=next_action,
        next_action_at=next_action_at,
        is_active=is_active,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def create_test_app(
    *,
    user: User,
) -> FastAPI:
    """Create a Lead API test application."""
    app = FastAPI()
    app.include_router(leads_router)

    def override_get_db_session():
        """Provide a database session to the test application."""
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
def make_test_client(
    *,
    user: User,
) -> TestClient:
    """Create a Lead API test client."""
    app = create_test_app(user=user)

    with TestClient(app) as client:
        yield client


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    """Set the tenant-selection header."""
    client.headers.update(
        {
            "X-Organization-ID": str(organization.id),
        }
    )


def test_create_lead_successfully() -> None:
    """Create a Lead within the verified tenant."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Rahul",
            last_name="Sharma",
            email="rahul@example.com",
            phone="+919876543210",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                    "interest": "HIGH",
                    "outcome": None,
                    "next_action": "Call customer",
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["contact_id"] == str(contact.id)
        assert payload["status"] == Lead.STATUS_NEW
        assert payload["interest"] == "HIGH"
        assert payload["outcome"] is None
        assert payload["owner_user_id"] is None
        assert payload["next_action"] == "Call customer"
        assert payload["next_action_at"] is None
        assert payload["is_active"] is True
        assert payload["created_at"]
        assert payload["updated_at"]


def test_create_lead_defaults_status_to_new() -> None:
    """A newly created Lead starts in the NEW lifecycle state."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="New",
            last_name="Lead",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["status"] == Lead.STATUS_NEW
        assert payload["owner_user_id"] is None


def test_create_lead_does_not_accept_client_organization_id() -> None:
    """Ignore client attempts to provide tenant ownership."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        other_organization = create_organization(db)
        db.commit()

        contact = create_contact(
            db,
            organization=organization,
            first_name="Tenant",
            last_name="Safe",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                    "organization_id": str(other_organization.id),
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["organization_id"] == str(organization.id)
        assert payload["organization_id"] != str(other_organization.id)


def test_create_lead_does_not_accept_client_owner_user_id() -> None:
    """DF-42 does not perform Lead ownership assignment."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Owner",
            last_name="Test",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                    "owner_user_id": str(user.id),
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["owner_user_id"] is None


def test_create_lead_requires_existing_contact() -> None:
    """Reject Lead creation when the Contact does not exist."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(uuid4()),
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Contact not found.",
        }


def test_create_lead_prevents_cross_tenant_contact() -> None:
    """Do not create a Lead for another tenant's Contact."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        organization_b = create_organization(db)

        contact_b = create_contact(
            db,
            organization=organization_b,
            first_name="Private",
            last_name="Contact",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact_b.id),
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Contact not found.",
        }

        with TestingSessionLocal() as verification_db:
            cross_tenant_lead = verification_db.scalar(
                select(Lead).where(
                    Lead.organization_id == organization_a.id,
                    Lead.contact_id == contact_b.id,
                )
            )

            assert cross_tenant_lead is None


def test_create_lead_requires_permission() -> None:
    """Reject Lead creation when leads.create is missing."""
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Protected",
        )

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_create_lead_requires_tenant_context() -> None:
    """Reject Lead creation without tenant context."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, _ = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(uuid4()),
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_create_lead_validates_contact_id() -> None:
    """Require contact_id to be a valid UUID."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": "not-a-uuid",
                },
            )

        assert response.status_code == 422


def test_create_lead_allows_optional_fields_to_be_omitted() -> None:
    """Create a Lead with only the required Contact reference."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Minimal",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["contact_id"] == str(contact.id)
        assert payload["status"] == Lead.STATUS_NEW
        assert payload["interest"] is None
        assert payload["outcome"] is None
        assert payload["owner_user_id"] is None
        assert payload["next_action"] is None
        assert payload["next_action_at"] is None


def test_create_lead_validates_interest_length() -> None:
    """Reject interest values exceeding the model length."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Interest",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                    "interest": "A" * 31,
                },
            )

        assert response.status_code == 422


def test_create_lead_validates_outcome_length() -> None:
    """Reject outcome values exceeding the model length."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Outcome",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                    "outcome": "A" * 31,
                },
            )

        assert response.status_code == 422


def test_create_lead_validates_next_action_length() -> None:
    """Reject next_action values exceeding the model length."""
    permission_key = "leads.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Next",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/leads",
                json={
                    "contact_id": str(contact.id),
                    "next_action": "A" * 501,
                },
            )

        assert response.status_code == 422


def test_get_lead_successfully() -> None:
    """Retrieve a Lead within the verified tenant."""
    permission_key = "leads.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Anita",
            last_name="Rao",
            email="anita@example.com",
            phone="+919876543211",
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            interest="MEDIUM",
            next_action="Follow up tomorrow",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/leads/{lead.id}",
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["id"] == str(lead.id)
        assert payload["organization_id"] == str(organization.id)
        assert payload["contact_id"] == str(contact.id)
        assert payload["status"] == Lead.STATUS_NEW
        assert payload["interest"] == "MEDIUM"
        assert payload["next_action"] == "Follow up tomorrow"
        assert payload["owner_user_id"] is None


def test_get_lead_returns_404_for_missing_lead() -> None:
    """Return 404 when the Lead does not exist."""
    permission_key = "leads.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/leads/{uuid4()}",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Lead not found.",
        }


def test_get_lead_prevents_cross_tenant_access() -> None:
    """Do not expose a Lead owned by another tenant."""
    permission_key = "leads.read"

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        organization_b = create_organization(db)

        contact_b = create_contact(
            db,
            organization=organization_b,
            first_name="Private",
            last_name="Contact",
        )

        lead_b = create_lead(
            db,
            organization=organization_b,
            contact=contact_b,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.get(
                f"/api/v1/leads/{lead_b.id}",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Lead not found.",
        }


def test_get_lead_requires_permission() -> None:
    """Reject Lead retrieval when leads.read is missing."""
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Protected",
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/leads/{lead.id}",
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_get_lead_requires_tenant_context() -> None:
    """Reject Lead retrieval without tenant context."""
    permission_key = "leads.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = create_contact(
            db,
            organization=organization,
            first_name="Missing",
            last_name="Tenant",
        )

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        with make_test_client(user=user) as client:
            response = client.get(
                f"/api/v1/leads/{lead.id}",
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_get_lead_validates_lead_id() -> None:
    """Require the Lead identifier to be a valid UUID."""
    permission_key = "leads.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/leads/not-a-uuid",
            )

        assert response.status_code == 422