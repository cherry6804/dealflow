"""Tests for DealFlow Customer Profile API routes."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.customer_profiles import router as customer_profiles_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
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
    """Create a unique test user."""
    user = User(
        email=f"user-{uuid4()}@example.com",
        display_name=f"Test User {uuid4()}",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(db: Session) -> Organization:
    """Create a unique test organization."""
    organization = Organization(
        name=f"Test Organization-{uuid4()}",
        is_active=True,
    )
    db.add(organization)
    db.flush()
    return organization


def create_contact(
    db: Session,
    *,
    organization: Organization,
    first_name: str = "Test",
    last_name: str | None = "Customer",
    email: str | None = None,
) -> Contact:
    """Create and persist a test Contact."""
    contact = Contact(
        organization_id=organization.id,
        first_name=first_name,
        last_name=last_name,
        email=email or f"contact-{uuid4()}@example.com",
        is_active=True,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def create_authorized_user(
    db: Session,
    *,
    permission_keys: tuple[str, ...],
) -> tuple[User, Organization]:
    """Create a user, tenant, membership, role, and permission grants."""
    user = create_user(db)
    organization = create_organization(db)

    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=True,
    )
    role = Role(
        name=f"Test Role-{uuid4()}",
        is_active=True,
    )
    db.add_all([membership, role])
    db.flush()

    db.add(
        MembershipRole(
            membership_id=membership.id,
            role_id=role.id,
        )
    )

    for key in permission_keys:
        permission = db.scalar(
            select(Permission).where(Permission.key == key)
        )
        if permission is None:
            permission = Permission(key=key, is_active=True)
            db.add(permission)
            db.flush()

        db.add(
            RolePermission(
                role_id=role.id,
                permission_id=permission.id,
            )
        )

    db.commit()
    return user, organization


def create_test_app(*, user: User) -> FastAPI:
    """Create a test application for Customer Profile routes."""
    app = FastAPI()
    app.include_router(customer_profiles_router)

    def override_get_db_session():
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
def make_test_client(*, user: User):
    """Create a Customer Profile API test client."""
    app = create_test_app(user=user)
    with TestClient(app) as client:
        yield client


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    """Set the tenant-selection header."""
    client.headers.update(
        {"X-Organization-ID": str(organization.id)}
    )


def test_create_customer_profile_successfully() -> None:
    """Explicitly register an existing Contact as a Customer."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("contacts.create",),
        )
        contact = create_contact(
            db,
            organization=organization,
            first_name="Anita",
            last_name="Rao",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/customer-profiles",
                json={
                    "contact_id": str(contact.id),
                    "customer_notes": "Interested in residential property.",
                },
            )

        assert response.status_code == 201, response.text
        payload = response.json()
        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["contact_id"] == str(contact.id)
        assert payload["is_active"] is True
        assert payload["customer_notes"] == (
            "Interested in residential property."
        )
        assert payload["contact"]["first_name"] == "Anita"


def test_create_customer_profile_rejects_contact_from_another_tenant() -> None:
    """A tenant cannot register another tenant's Contact."""
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_keys=("contacts.create",),
        )
        organization_b = create_organization(db)
        foreign_contact = create_contact(
            db,
            organization=organization_b,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)
            response = client.post(
                "/api/v1/customer-profiles",
                json={"contact_id": str(foreign_contact.id)},
            )

        assert response.status_code == 404


def test_create_customer_profile_rejects_duplicate_registration() -> None:
    """A Contact cannot be registered as a Customer twice."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("contacts.create",),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            first_response = client.post(
                "/api/v1/customer-profiles",
                json={"contact_id": str(contact.id)},
            )
            second_response = client.post(
                "/api/v1/customer-profiles",
                json={"contact_id": str(contact.id)},
            )

        assert first_response.status_code == 201, first_response.text
        assert second_response.status_code == 409


def test_list_customer_profiles_returns_registered_customers() -> None:
    """List Customer Profiles without treating every Contact as a Customer."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("contacts.read", "contacts.create"),
        )
        customer_contact = create_contact(
            db,
            organization=organization,
            first_name="Registered",
        )
        create_contact(
            db,
            organization=organization,
            first_name="NotRegistered",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            create_response = client.post(
                "/api/v1/customer-profiles",
                json={"contact_id": str(customer_contact.id)},
            )
            list_response = client.get("/api/v1/customer-profiles")

        assert create_response.status_code == 201, create_response.text
        assert list_response.status_code == 200, list_response.text
        payload = list_response.json()
        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["contact_id"] == str(customer_contact.id)


def test_get_customer_profile_returns_404_for_missing_profile() -> None:
    """Return 404 when a Customer Profile does not exist."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("contacts.read",),
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"/api/v1/customer-profiles/{uuid4()}"
            )

        assert response.status_code == 404


def test_patch_customer_profile_updates_notes() -> None:
    """PATCH changes supplied fields without changing omitted fields."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("contacts.create", "contacts.update"),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            create_response = client.post(
                "/api/v1/customer-profiles",
                json={
                    "contact_id": str(contact.id),
                    "customer_notes": "Original notes",
                },
            )
            assert create_response.status_code == 201, create_response.text
            profile_id = create_response.json()["id"]

            update_response = client.patch(
                f"/api/v1/customer-profiles/{profile_id}",
                json={"customer_notes": "Updated notes"},
            )

        assert update_response.status_code == 200, update_response.text
        payload = update_response.json()
        assert payload["customer_notes"] == "Updated notes"
        assert payload["is_active"] is True


def test_put_customer_profile_replaces_editable_fields() -> None:
    """PUT replaces the supplied editable profile fields."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("contacts.create", "contacts.update"),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            create_response = client.post(
                "/api/v1/customer-profiles",
                json={"contact_id": str(contact.id)},
            )
            assert create_response.status_code == 201, create_response.text
            profile_id = create_response.json()["id"]

            update_response = client.put(
                f"/api/v1/customer-profiles/{profile_id}",
                json={
                    "customer_notes": "Updated using PUT",
                    "is_active": False,
                },
            )

        assert update_response.status_code == 200, update_response.text
        payload = update_response.json()
        assert payload["customer_notes"] == "Updated using PUT"
        assert payload["is_active"] is False


def test_delete_customer_profile_deactivates_instead_of_removing() -> None:
    """DELETE preserves the profile but marks it inactive."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("contacts.create", "contacts.update"),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            create_response = client.post(
                "/api/v1/customer-profiles",
                json={"contact_id": str(contact.id)},
            )
            assert create_response.status_code == 201, create_response.text
            profile_id = create_response.json()["id"]

            delete_response = client.delete(
                f"/api/v1/customer-profiles/{profile_id}"
            )

        assert delete_response.status_code == 200, delete_response.text
        assert delete_response.json()["is_active"] is False

        persisted_profile = db.scalar(
            select(CustomerProfile).where(
                CustomerProfile.id == UUID(profile_id),
                CustomerProfile.organization_id == organization.id,
            )
        )
        assert persisted_profile is not None
        assert persisted_profile.is_active is False


def test_customer_profile_routes_require_permissions() -> None:
    """Reject requests when the user lacks the required permission."""
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

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get("/api/v1/customer-profiles")

        assert response.status_code == 403
        assert response.json() == {"detail": "Permission denied."}
