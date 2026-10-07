"""Tests for DealFlow Property API routes."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from uuid import UUID, uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.properties import router as properties_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.property import Property
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


def create_test_app(
    *,
    user: User,
) -> FastAPI:
    """Create a Property API test application."""
    app = FastAPI()
    app.include_router(properties_router)

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
    """Create a Property API test client."""
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


def test_create_property_successfully() -> None:
    """Create a Property within the verified tenant."""
    permission_key = "properties.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/properties",
                json={},
            )

        assert response.status_code == 201

        payload = response.json()

        assert UUID(payload["id"])
        assert payload["organization_id"] == str(organization.id)
        assert payload["created_at"]
        assert payload["updated_at"]


def test_create_property_persists_to_database() -> None:
    """Persist the newly created Property in the verified tenant."""
    permission_key = "properties.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/properties",
                json={},
            )

        assert response.status_code == 201

        property_id = UUID(response.json()["id"])

        verification_db = TestingSessionLocal()

        try:
            property_record = verification_db.scalar(
                select(Property).where(
                    Property.id == property_id,
                )
            )

            assert property_record is not None
            assert property_record.organization_id == organization.id
        finally:
            verification_db.close()


def test_create_property_does_not_accept_client_organization_id() -> None:
    """Ignore client attempts to provide tenant ownership."""
    permission_key = "properties.create"

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
                "/api/v1/properties",
                json={
                    "organization_id": str(other_organization.id),
                },
            )

        assert response.status_code == 201

        payload = response.json()

        assert payload["organization_id"] == str(organization.id)
        assert payload["organization_id"] != str(other_organization.id)


def test_create_property_requires_permission() -> None:
    """Reject Property creation when properties.create is missing."""
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
                "/api/v1/properties",
                json={},
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_create_property_requires_tenant_context() -> None:
    """Reject Property creation without tenant context."""
    permission_key = "properties.create"

    with TestingSessionLocal() as db:
        user, _ = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            response = client.post(
                "/api/v1/properties",
                json={},
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_create_property_generates_unique_ids() -> None:
    """Generate distinct identifiers for separate Property records."""
    permission_key = "properties.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            first_response = client.post(
                "/api/v1/properties",
                json={},
            )
            second_response = client.post(
                "/api/v1/properties",
                json={},
            )

        assert first_response.status_code == 201
        assert second_response.status_code == 201

        first_id = first_response.json()["id"]
        second_id = second_response.json()["id"]

        assert UUID(first_id)
        assert UUID(second_id)
        assert first_id != second_id


def test_create_property_is_tenant_scoped() -> None:
    """Persist a created Property under the verified tenant only."""
    permission_key = "properties.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/properties",
                json={},
            )

        assert response.status_code == 201

        property_id = UUID(response.json()["id"])

        property_record = db.scalar(
            select(Property).where(
                Property.id == property_id,
            )
        )

        assert property_record is not None
        assert property_record.organization_id == organization.id

def test_update_property_commercial_successfully() -> None:
    """Update all commercial fields for a Property."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        property_record = Property(
            organization_id=organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "SALE",
                    "price": "12500000.00",
                    "currency": "INR",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": "2500.00",
                },
            )

        assert response.status_code == 200

        payload = response.json()

        assert payload["id"] == str(property_id)
        assert payload["organization_id"] == str(organization.id)
        assert payload["transaction_type"] == "SALE"
        assert payload["price"] == "12500000.00"
        assert payload["currency"] == "INR"
        assert payload["rent"] is None
        assert payload["security_deposit"] is None
        assert payload["maintenance_charge"] == "2500.00"


def test_update_property_commercial_persists_to_database() -> None:
    """Persist updated commercial fields in the database."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        property_record = Property(
            organization_id=organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "RENT",
                    "price": None,
                    "currency": "INR",
                    "rent": "45000.00",
                    "security_deposit": "90000.00",
                    "maintenance_charge": "3500.00",
                },
            )

        assert response.status_code == 200

        verification_db = TestingSessionLocal()

        try:
            updated_property = verification_db.scalar(
                select(Property).where(
                    Property.id == property_id,
                )
            )

            assert updated_property is not None
            assert updated_property.organization_id == organization.id
            assert updated_property.transaction_type == "RENT"
            assert updated_property.price is None
            assert updated_property.currency == "INR"
            assert updated_property.rent == Decimal("45000.00")
            assert updated_property.security_deposit == Decimal("90000.00")
            assert updated_property.maintenance_charge == Decimal("3500.00")
        finally:
            verification_db.close()


def test_update_property_commercial_requires_permission() -> None:
    """Reject commercial updates without properties.update permission."""

    with TestingSessionLocal() as db:
        user = create_user(db)
        organization = create_organization(db)

        create_membership(
            db,
            user=user,
            organization=organization,
        )

        property_record = Property(
            organization_id=organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "SALE",
                    "price": "1000000.00",
                    "currency": "INR",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": None,
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Permission denied.",
        }


def test_update_property_commercial_requires_tenant_context() -> None:
    """Reject commercial updates without tenant context."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        property_record = Property(
            organization_id=organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "SALE",
                    "price": "1000000.00",
                    "currency": "INR",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": None,
                },
            )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "Organization context is required.",
        }


def test_update_property_commercial_is_tenant_scoped() -> None:
    """Do not update a Property belonging to another tenant."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        other_organization = create_organization(db)

        property_record = Property(
            organization_id=other_organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "SALE",
                    "price": "1000000.00",
                    "currency": "INR",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": None,
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Property not found.",
        }

        verification_db = TestingSessionLocal()

        try:
            unchanged_property = verification_db.scalar(
                select(Property).where(
                    Property.id == property_id,
                )
            )

            assert unchanged_property is not None
            assert unchanged_property.organization_id == other_organization.id
            assert unchanged_property.transaction_type is None
            assert unchanged_property.price is None
            assert unchanged_property.currency is None
            assert unchanged_property.rent is None
            assert unchanged_property.security_deposit is None
            assert unchanged_property.maintenance_charge is None
        finally:
            verification_db.close()


def test_update_property_commercial_validates_transaction_type() -> None:
    """Reject unsupported transaction types."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        property_record = Property(
            organization_id=organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "INVALID",
                    "price": "1000000.00",
                    "currency": "INR",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": None,
                },
            )

        assert response.status_code == 422


def test_update_property_commercial_validates_currency() -> None:
    """Reject invalid currency codes."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        property_record = Property(
            organization_id=organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "SALE",
                    "price": "1000000.00",
                    "currency": "IN",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": None,
                },
            )

        assert response.status_code == 422


def test_update_property_commercial_validates_non_negative_amounts() -> None:
    """Reject negative commercial monetary values."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        property_record = Property(
            organization_id=organization.id,
        )
        db.add(property_record)
        db.commit()
        db.refresh(property_record)

        property_id = property_record.id

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{property_id}/commercial",
                json={
                    "transaction_type": "SALE",
                    "price": "-1.00",
                    "currency": "INR",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": None,
                },
            )

        assert response.status_code == 422


def test_update_property_commercial_returns_not_found_for_unknown_property() -> None:
    """Return 404 when the Property does not exist in the tenant."""

    permission_key = "properties.update"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        unknown_property_id = uuid4()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.patch(
                f"/api/v1/properties/{unknown_property_id}/commercial",
                json={
                    "transaction_type": "SALE",
                    "price": "1000000.00",
                    "currency": "INR",
                    "rent": None,
                    "security_deposit": None,
                    "maintenance_charge": None,
                },
            )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "Property not found.",
        }