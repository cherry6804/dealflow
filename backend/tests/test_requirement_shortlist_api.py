
from __future__ import annotations

from uuid import uuid4
from sqlalchemy import select
from app.db.models import Property
from tests.test_customer_requirements_api import (
    TestingSessionLocal,
    add_tenant_header,
    create_authorized_user,
    create_customer_requirement,
    make_test_client,
    get_or_create_permission,
assign_permission_to_role,
)
from app.db.models import Membership, MembershipRole, RolePermission, Role
def create_property(db, organization_id):
    property_record = Property(organization_id=organization_id)
    db.add(property_record)
    db.commit()
    db.refresh(property_record)
    return property_record


def test_add_property_to_requirement_shortlist() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )
        requirement = create_customer_requirement(db, organization=organization)
        property_record = create_property(db, organization.id)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/shortlist",
                json={"property_id": str(property_record.id)},
            )

        assert response.status_code == 201
        payload = response.json()
        assert payload["property"]["id"] == str(property_record.id)
        assert payload["created_by_user_id"] == str(user.id)


def test_add_duplicate_property_to_shortlist_returns_conflict() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )
        requirement = create_customer_requirement(db, organization=organization)
        property_record = create_property(db, organization.id)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            url = (
                f"/api/v1/customer-requirements/{requirement.id}/shortlist"
            )
            first = client.post(
                url,
                json={"property_id": str(property_record.id)},
            )
            second = client.post(
                url,
                json={"property_id": str(property_record.id)},
            )

        assert first.status_code == 201
        assert second.status_code == 409


def test_list_requirement_shortlist_returns_items() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(db, organization=organization)
        property_record = create_property(db, organization.id)

        # Add the shortlist record directly so this test only requires
        # read permission and tests the list endpoint independently.
        from app.db.models import RequirementPropertyShortlist

        shortlist_record = RequirementPropertyShortlist(
            organization_id=organization.id,
            customer_requirement_id=requirement.id,
            property_id=property_record.id,
            created_by_user_id=user.id,
        )
        db.add(shortlist_record)
        db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"/api/v1/customer-requirements/{requirement.id}/shortlist"
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["requirement_id"] == str(requirement.id)
        assert payload["total"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["property"]["id"] == str(property_record.id)


def test_remove_property_from_requirement_shortlist() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organization_id == organization.id,
            )
        )
        assert membership is not None

        membership_role = db.scalar(
            select(MembershipRole).where(
                MembershipRole.membership_id == membership.id,
            )
        )
        assert membership_role is not None

        role = db.get(Role, membership_role.role_id)
        assert role is not None

        read_permission = get_or_create_permission(
            db,
            key="requirements.read",
        )
        assign_permission_to_role(
            db,
            role=role,
            permission=read_permission,
        )
        db.commit()
        requirement = create_customer_requirement(db, organization=organization)
        property_record = create_property(db, organization.id)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            url = (
                f"/api/v1/customer-requirements/{requirement.id}/shortlist"
            )
            add_response = client.post(
                url,
                json={"property_id": str(property_record.id)},
            )
            assert add_response.status_code == 201

            delete_response = client.delete(
                f"{url}/{property_record.id}"
            )

            assert delete_response.status_code == 204

            list_response = client.get(url)

        assert list_response.status_code == 200
        assert list_response.json()["total"] == 0


def test_shortlist_rejects_property_from_another_tenant() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )
        other_organization_user, other_organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )
        requirement = create_customer_requirement(db, organization=organization)
        other_property = create_property(db, other_organization.id)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"/api/v1/customer-requirements/{requirement.id}/shortlist",
                json={"property_id": str(other_property.id)},
            )

        assert response.status_code == 404


def test_shortlist_returns_not_found_for_another_tenants_requirement() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        _, other_organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        other_requirement = create_customer_requirement(db, organization=other_organization)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.get(
                f"/api/v1/customer-requirements/{other_requirement.id}/shortlist"
            )

        assert response.status_code == 404
