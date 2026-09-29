"""Tests for DealFlow Contact API routes."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contacts import router as contacts_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.contact import Contact
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


def create_test_app(
    *,
    user: User,
) -> FastAPI:
    """Create a Contact API test application."""
    app = FastAPI()
    app.include_router(contacts_router)

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
    """Create a Contact API test client."""
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


def test_create_contact_successfully() -> None:
    """Create a Contact within the verified tenant."""
    permission_key = "contacts.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/contacts",
                json={
                    "first_name": "Rahul",
                    "last_name": "Sharma",
                    "email": "rahul@example.com",
                    "phone": "+919876543210",
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["first_name"] == "Rahul"
        assert payload["last_name"] == "Sharma"
        assert payload["email"] == "rahul@example.com"
        assert payload["phone"] == "+919876543210"
        assert payload["is_active"] is True
        assert payload["created_at"]
        assert payload["updated_at"]


def test_create_contact_does_not_accept_client_organization_id() -> None:
    """Ignore client attempts to provide tenant ownership."""
    permission_key = "contacts.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        other_organization = create_organization(db)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/contacts",
                json={
                    "first_name": "Tenant",
                    "last_name": "Safe",
                    "organization_id": str(other_organization.id),
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["organization_id"] == str(organization.id)
        assert payload["organization_id"] != str(other_organization.id)


def test_create_contact_requires_permission() -> None:
    """Reject Contact creation when permission is missing."""
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/contacts",
                json={
                    "first_name": "Unauthorized",
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_create_contact_requires_tenant_context() -> None:
    """Reject Contact creation without tenant context."""
    permission_key = "contacts.create"

    with TestingSessionLocal() as db:
        user, _ = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            response = client.post(
                "/api/v1/contacts",
                json={
                    "first_name": "Missing",
                    "last_name": "Tenant",
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_get_contact_successfully() -> None:
    """Retrieve a Contact within the verified tenant."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contact = Contact(
            organization_id=organization.id,
            first_name="Anita",
            last_name="Rao",
            email="anita@example.com",
            phone="+919876543211",
            is_active=True,
        )

        db.add(contact)
        db.commit()
        db.refresh(contact)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/contacts/{contact.id}",
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["id"] == str(contact.id)
        assert payload["organization_id"] == str(organization.id)
        assert payload["first_name"] == "Anita"
        assert payload["last_name"] == "Rao"


def test_get_contact_returns_404_for_missing_contact() -> None:
    """Return 404 when the Contact does not exist."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                f"/api/v1/contacts/{uuid4()}",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Contact not found.",
        }


def test_get_contact_prevents_cross_tenant_access() -> None:
    """Do not expose a Contact owned by another tenant."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        organization_b = create_organization(db)

        contact_b = Contact(
            organization_id=organization_b.id,
            first_name="Private",
            last_name="Contact",
            email="private@example.com",
            phone="+919876543212",
            is_active=True,
        )

        db.add(contact_b)
        db.commit()
        db.refresh(contact_b)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.get(
                f"/api/v1/contacts/{contact_b.id}",
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Contact not found.",
        }


def test_create_contact_validates_required_first_name() -> None:
    """Require first_name when creating a Contact."""
    permission_key = "contacts.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/contacts",
                json={
                    "last_name": "MissingFirstName",
                },
            )

        assert response.status_code == 422


def test_create_contact_validates_field_lengths() -> None:
    """Reject Contact fields exceeding their defined lengths."""
    permission_key = "contacts.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/contacts",
                json={
                    "first_name": "A" * 101,
                    "last_name": "B" * 101,
                    "email": "C" * 321,
                    "phone": "D" * 51,
                },
            )

        assert response.status_code == 422


def test_create_contact_allows_optional_contact_fields_to_be_omitted() -> None:
    """Allow creation with only the required Contact identity field."""
    permission_key = "contacts.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/contacts",
                json={
                    "first_name": "Minimal",
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["first_name"] == "Minimal"
        assert payload["last_name"] is None
        assert payload["email"] is None
        assert payload["phone"] is None


def test_list_contacts_successfully() -> None:
    """List Contacts within the verified tenant."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        first_contact = create_contact(
            db,
            organization=organization,
            first_name="Rahul",
            last_name="Sharma",
            email="rahul@example.com",
            phone="+919876543210",
        )
        second_contact = create_contact(
            db,
            organization=organization,
            first_name="Anita",
            last_name="Rao",
            email="anita@example.com",
            phone="+919876543211",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get("/api/v1/contacts")

        assert response.status_code == 200

        payload = response.json()

        assert payload["page"] == 1
        assert payload["page_size"] == 20
        assert payload["total"] == 2
        assert payload["total_pages"] == 1
        assert len(payload["items"]) == 2

        returned_ids = {item["id"] for item in payload["items"]}

        assert str(first_contact.id) in returned_ids
        assert str(second_contact.id) in returned_ids


def test_list_contacts_uses_default_pagination() -> None:
    """Use the documented default pagination values."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        for index in range(3):
            create_contact(
                db,
                organization=organization,
                first_name=f"Contact{index}",
            )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get("/api/v1/contacts")

        assert response.status_code == 200

        payload = response.json()

        assert payload["page"] == 1
        assert payload["page_size"] == 20
        assert payload["total"] == 3
        assert payload["total_pages"] == 1
        assert len(payload["items"]) == 3


def test_list_contacts_supports_pagination() -> None:
    """Return the requested page and pagination metadata."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        contacts = [
            create_contact(
                db,
                organization=organization,
                first_name=f"Contact{index}",
            )
            for index in range(5)
        ]

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={
                    "page": 2,
                    "page_size": 2,
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["page"] == 2
        assert payload["page_size"] == 2
        assert payload["total"] == 5
        assert payload["total_pages"] == 3
        assert len(payload["items"]) == 2

        expected_ids = {
            str(contacts[1].id),
            str(contacts[2].id),
        }
        returned_ids = {
            item["id"]
            for item in payload["items"]
        }

        assert returned_ids == expected_ids


def test_list_contacts_searches_first_name() -> None:
    """Search Contacts by first name."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        matching_contact = create_contact(
            db,
            organization=organization,
            first_name="Rahul",
            last_name="Sharma",
        )
        create_contact(
            db,
            organization=organization,
            first_name="Anita",
            last_name="Rao",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"search": "Rahul"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["total"] == 1
        assert payload["total_pages"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["id"] == str(matching_contact.id)


def test_list_contacts_searches_last_name() -> None:
    """Search Contacts by last name."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        matching_contact = create_contact(
            db,
            organization=organization,
            first_name="Rahul",
            last_name="Sharma",
        )
        create_contact(
            db,
            organization=organization,
            first_name="Anita",
            last_name="Rao",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"search": "Sharma"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["id"] == str(matching_contact.id)


def test_list_contacts_searches_email() -> None:
    """Search Contacts by email."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        matching_contact = create_contact(
            db,
            organization=organization,
            first_name="Rahul",
            email="rahul.sharma@example.com",
        )
        create_contact(
            db,
            organization=organization,
            first_name="Anita",
            email="anita.rao@example.com",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"search": "rahul.sharma@example.com"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["total"] == 1
        assert payload["items"][0]["id"] == str(matching_contact.id)


def test_list_contacts_searches_phone() -> None:
    """Search Contacts by phone."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        matching_contact = create_contact(
            db,
            organization=organization,
            first_name="Rahul",
            phone="+919876543210",
        )
        create_contact(
            db,
            organization=organization,
            first_name="Anita",
            phone="+919876543211",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"search": "9876543210"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["total"] == 1
        assert payload["items"][0]["id"] == str(matching_contact.id)


def test_list_contacts_search_is_case_insensitive() -> None:
    """Perform case-insensitive Contact searches."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        matching_contact = create_contact(
            db,
            organization=organization,
            first_name="Rahul",
            last_name="Sharma",
            email="Rahul.Sharma@example.com",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"search": "RAHUL"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["total"] == 1
        assert payload["items"][0]["id"] == str(matching_contact.id)


def test_list_contacts_filters_active_contacts() -> None:
    """Return only active Contacts when requested."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        active_contact = create_contact(
            db,
            organization=organization,
            first_name="Active",
            is_active=True,
        )
        create_contact(
            db,
            organization=organization,
            first_name="Inactive",
            is_active=False,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"is_active": "true"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["id"] == str(active_contact.id)
        assert payload["items"][0]["is_active"] is True


def test_list_contacts_filters_inactive_contacts() -> None:
    """Return only inactive Contacts when requested."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        create_contact(
            db,
            organization=organization,
            first_name="Active",
            is_active=True,
        )
        inactive_contact = create_contact(
            db,
            organization=organization,
            first_name="Inactive",
            is_active=False,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"is_active": "false"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["id"] == str(inactive_contact.id)
        assert payload["items"][0]["is_active"] is False


def test_list_contacts_returns_empty_result() -> None:
    """Return an empty successful response when no Contacts match."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"search": "does-not-exist"},
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["items"] == []
        assert payload["page"] == 1
        assert payload["page_size"] == 20
        assert payload["total"] == 0
        assert payload["total_pages"] == 0


def test_list_contacts_prevents_cross_tenant_access() -> None:
    """Never return Contacts belonging to another tenant."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        organization_b = create_organization(db)

        contact_a = create_contact(
            db,
            organization=organization_a,
            first_name="Visible",
        )
        contact_b = create_contact(
            db,
            organization=organization_b,
            first_name="Private",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)

            response = client.get("/api/v1/contacts")

        assert response.status_code == 200

        payload = response.json()

        returned_ids = {
            item["id"]
            for item in payload["items"]
        }

        assert str(contact_a.id) in returned_ids
        assert str(contact_b.id) not in returned_ids
        assert payload["total"] == 1


def test_list_contacts_requires_permission() -> None:
    """Reject Contact listing when contacts.read is missing."""
    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        create_contact(
            db,
            organization=organization,
            first_name="Protected",
        )

        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get("/api/v1/contacts")

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_list_contacts_requires_tenant_context() -> None:
    """Reject Contact listing without tenant context."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, _ = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            response = client.get("/api/v1/contacts")

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_list_contacts_validates_page() -> None:
    """Reject page values below one."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"page": 0},
            )

        assert response.status_code == 422


def test_list_contacts_validates_page_size_lower_bound() -> None:
    """Reject page_size values below one."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"page_size": 0},
            )

        assert response.status_code == 422


def test_list_contacts_validates_page_size_upper_bound() -> None:
    """Reject page_size values above the maximum."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get(
                "/api/v1/contacts",
                params={"page_size": 101},
            )

        assert response.status_code == 422


def test_list_contacts_uses_deterministic_ordering() -> None:
    """Return Contacts in the service-defined deterministic order."""
    permission_key = "contacts.read"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        first_contact = create_contact(
            db,
            organization=organization,
            first_name="First",
        )
        second_contact = create_contact(
            db,
            organization=organization,
            first_name="Second",
        )
        third_contact = create_contact(
            db,
            organization=organization,
            first_name="Third",
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.get("/api/v1/contacts")

        assert response.status_code == 200

        payload = response.json()

        returned_ids = [
            item["id"]
            for item in payload["items"]
        ]

        assert returned_ids == [
            str(third_contact.id),
            str(second_contact.id),
            str(first_contact.id),
        ]