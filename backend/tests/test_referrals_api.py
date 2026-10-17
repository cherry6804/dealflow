
"""Tests for the tenant-scoped Referral API."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.referrals import router as referrals_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.contact import Contact
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.referral import Referral
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
    first_name: str = "Referral",
    last_name: str | None = "Contact",
) -> Contact:
    """Create a persisted contact in the specified organization."""
    contact = Contact(
        organization_id=organization.id,
        first_name=first_name,
        last_name=last_name,
        email=f"contact-{uuid4()}@example.com",
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
    """Create a user with an organization and specified permissions."""
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
    """Create a test application for Referral routes."""
    app = FastAPI()
    app.include_router(referrals_router)

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
    """Create a Referral API test client."""
    app = create_test_app(user=user)
    with TestClient(app) as client:
        yield client


def add_tenant_header(
    client: TestClient,
    organization: Organization,
) -> None:
    """Select the organization for the request."""
    client.headers.update(
        {"X-Organization-ID": str(organization.id)}
    )


def create_referral_payload(contact: Contact) -> dict:
    """Return a valid referral payload."""
    return {
        "referral_name": "Priya Sharma",
        "referral_phone": "+91-9876543210",
        "referral_email": "priya@example.com",
        "referrer_contact_id": str(contact.id),
        "status": "NEW",
        "notes": "Interested in a residential property.",
    }


def test_create_referral_successfully() -> None:
    """Create and persist a referral in the active organization."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("referrals.create",),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/referrals",
                json=create_referral_payload(contact),
            )

        assert response.status_code == 201, response.text
        payload = response.json()
        referral_id = UUID(payload["id"])

        assert payload["organization_id"] == str(organization.id)
        assert payload["referrer_contact_id"] == str(contact.id)
        assert payload["referral_name"] == "Priya Sharma"
        assert payload["referral_email"] == "priya@example.com"
        assert payload["status"] == "NEW"
        assert payload["is_active"] is True

        persisted = db.scalar(
            select(Referral).where(Referral.id == referral_id)
        )
        assert persisted is not None
        assert persisted.created_by_user_id == user.id


def test_create_referral_requires_an_association() -> None:
    """Reject a referral with no customer, contact, or deal association."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("referrals.create",),
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                "/api/v1/referrals",
                json={"referral_name": "Priya Sharma"},
            )

        assert response.status_code == 422


def test_create_referral_rejects_contact_from_another_tenant() -> None:
    """Prevent linking a referral to another organization's contact."""
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_keys=("referrals.create",),
        )
        organization_b = create_organization(db)
        foreign_contact = create_contact(
            db,
            organization=organization_b,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)
            response = client.post(
                "/api/v1/referrals",
                json=create_referral_payload(foreign_contact),
            )

        assert response.status_code == 409, response.text


def test_list_referrals_supports_search_and_status_filter() -> None:
    """Search referrals and filter by status."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("referrals.create", "referrals.read"),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            first = client.post(
                "/api/v1/referrals",
                json=create_referral_payload(contact),
            )
            assert first.status_code == 201, first.text

            second = client.post(
                "/api/v1/referrals",
                json={
                    **create_referral_payload(contact),
                    "referral_name": "Arun Kumar",
                    "referral_email": "arun@example.com",
                },
            )
            assert second.status_code == 201, second.text

            update = client.patch(
                f"/api/v1/referrals/{second.json()['id']}",
                json={"status": "CONTACTED"},
            )
            # This test user has no referrals.update permission.
            assert update.status_code == 403

            search_response = client.get(
                "/api/v1/referrals",
                params={"search": "Priya"},
            )

        assert search_response.status_code == 200, search_response.text
        search_payload = search_response.json()
        assert search_payload["total"] == 1
        assert search_payload["items"][0]["referral_name"] == "Priya Sharma"


def test_get_referral_returns_404_for_another_tenant() -> None:
    """A referral is not visible through a different tenant context."""
    with TestingSessionLocal() as db:
        # Create a referral owned by organization A.
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=("referrals.create", "referrals.read"),
        )
        contact_a = create_contact(db, organization=organization_a)

        with make_test_client(user=user_a) as client_a:
            add_tenant_header(client_a, organization_a)
            create_response = client_a.post(
                "/api/v1/referrals",
                json=create_referral_payload(contact_a),
            )

        assert create_response.status_code == 201, create_response.text
        referral_id = create_response.json()["id"]

        # Create a different user who belongs to organization B.
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=("referrals.read",),
        )

        # Organization B must not be able to access organization A's referral.
        with make_test_client(user=user_b) as client_b:
            add_tenant_header(client_b, organization_b)
            response = client_b.get(
                f"/api/v1/referrals/{referral_id}"
            )

        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "Referral not found."}



def test_patch_referral_updates_supplied_fields() -> None:
    """Update a referral without overwriting omitted fields."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "referrals.create",
                "referrals.read",
                "referrals.update",
            ),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            create_response = client.post(
                "/api/v1/referrals",
                json=create_referral_payload(contact),
            )
            assert create_response.status_code == 201, create_response.text
            referral_id = create_response.json()["id"]

            update_response = client.patch(
                f"/api/v1/referrals/{referral_id}",
                json={
                    "status": "CONTACTED",
                    "notes": "Initial call completed.",
                },
            )

        assert update_response.status_code == 200, update_response.text
        payload = update_response.json()
        assert payload["status"] == "CONTACTED"
        assert payload["notes"] == "Initial call completed."
        assert payload["referral_name"] == "Priya Sharma"
        assert payload["is_active"] is True


def test_delete_referral_deactivates_instead_of_removing() -> None:
    """DELETE should preserve the referral record as inactive."""
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "referrals.create",
                "referrals.read",
                "referrals.update",
            ),
        )
        contact = create_contact(db, organization=organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            create_response = client.post(
                "/api/v1/referrals",
                json=create_referral_payload(contact),
            )
            assert create_response.status_code == 201, create_response.text
            referral_id = UUID(create_response.json()["id"])

            delete_response = client.delete(
                f"/api/v1/referrals/{referral_id}"
            )
            list_response = client.get("/api/v1/referrals")

        assert delete_response.status_code == 204, delete_response.text
        assert list_response.status_code == 200, list_response.text
        assert list_response.json()["total"] == 0

        persisted = db.scalar(
            select(Referral).where(Referral.id == referral_id)
        )
        assert persisted is not None
        assert persisted.is_active is False


def test_referral_routes_require_permissions() -> None:
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
            response = client.get("/api/v1/referrals")

        assert response.status_code == 403
        assert response.json() == {"detail": "Permission denied."}


def test_referral_requires_organization_header() -> None:
    """Reject referral requests without an organization selection."""
    with TestingSessionLocal() as db:
        user, _organization = create_authorized_user(
            db,
            permission_keys=("referrals.read",),
        )

        with make_test_client(user=user) as client:
            response = client.get("/api/v1/referrals")

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required."
        }
