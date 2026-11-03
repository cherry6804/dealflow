"""Owner-only permissions: templates, backend enforcement and alternate paths (E13 hardening).

Governance management and provider credential management are owner-only. These tests check the
role template, the permission check itself, the API surface, and role assignment. Positive cases
show legitimate Admin read access still works.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.authz.dependencies import permission_granted
from app.authz.permissions import (
    OWNER_ONLY_PERMISSION_KEYS,
    OWNER_ROLE_NAME,
    PERMISSION_CATALOG,
)
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.session import SessionLocal
from app.governance.capabilities import AUTOMATION_MASTER
from app.team.service import (
    DEFAULT_ROLE_TEMPLATES,
    _get_assignable_role,
    provision_default_organization_roles,
)
from app.tenant.dependencies import TenantContext
from tests.test_deals_api import create_membership, create_organization, create_user
from tests.test_governance_api import _app_for as governance_app_for
from tests.test_provider_secrets import _app_for as provider_app_for
from tests.test_team_api import attach_role

GOVERNANCE = "/api/v1/governance/capabilities"
PROVIDERS = "/api/v1/provider-credentials"
READ_GOVERNANCE_KEYS = ("governance.capabilities.read", "governance.usage.read", "governance.privacy.read")


def _org_with_provisioned_roles(db, *, owner: bool):
    """Create a user and organization with the standard roles; the user gets Owner or Admin."""
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(db, user=user, organization=organization)
    provision_default_organization_roles(db, organization_id=organization.id)
    role_name = OWNER_ROLE_NAME if owner else "Admin"
    role = db.scalar(
        select(Role).where(Role.organization_id == organization.id, Role.name == role_name)
    ) or db.scalar(select(Role).where(Role.organization_id.is_(None), Role.name == role_name))
    attach_role(db, membership=membership, role=role)
    db.commit()
    db.refresh(user)
    db.refresh(organization)
    db.refresh(membership)
    db.expunge(user)
    db.expunge(organization)
    db.expunge(membership)
    return user, organization, membership


def create_admin(*, permissions: tuple[str, ...] = ()):
    with SessionLocal() as db:
        return _org_with_provisioned_roles(db, owner=False)


def create_owner():
    with SessionLocal() as db:
        return _org_with_provisioned_roles(db, owner=True)


def _custom_role_with(db, *, organization_id, permission_key: str, membership: Membership) -> Role:
    role = Role(name=f"Custom {permission_key}", organization_id=organization_id, is_system=False, is_active=True)
    db.add(role)
    db.flush()
    permission = db.scalar(select(Permission).where(Permission.key == permission_key))
    db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.add(MembershipRole(membership_id=membership.id, role_id=role.id))
    db.flush()
    return role


# --- role templates ----------------------------------------------------------------------------


def test_admin_template_excludes_every_owner_only_key() -> None:
    admin_keys = set(DEFAULT_ROLE_TEMPLATES["Admin"])
    assert admin_keys.isdisjoint(OWNER_ONLY_PERMISSION_KEYS)


def test_admin_template_keeps_legitimate_governance_read_access() -> None:
    admin_keys = set(DEFAULT_ROLE_TEMPLATES["Admin"])
    assert set(READ_GOVERNANCE_KEYS) <= admin_keys


def test_owner_template_holds_every_catalogue_permission() -> None:
    assert set(DEFAULT_ROLE_TEMPLATES["DealFlow Owner"]) == {key for key, _ in PERMISSION_CATALOG}


@pytest.mark.parametrize("role_name", [name for name in DEFAULT_ROLE_TEMPLATES if name != "DealFlow Owner"])
def test_no_non_owner_template_holds_an_owner_only_key(role_name: str) -> None:
    assert set(DEFAULT_ROLE_TEMPLATES[role_name]).isdisjoint(OWNER_ONLY_PERMISSION_KEYS)


# --- backend permission check ------------------------------------------------------------------


@pytest.mark.parametrize("permission_key", sorted(OWNER_ONLY_PERMISSION_KEYS))
def test_admin_is_denied_each_owner_only_key_and_owner_is_allowed(permission_key: str) -> None:
    with SessionLocal() as db:
        _, admin_org, admin_membership = _org_with_provisioned_roles(db, owner=False)
        _, owner_org, owner_membership = _org_with_provisioned_roles(db, owner=True)
        admin_context = TenantContext(organization=admin_org, membership=admin_membership)
        owner_context = TenantContext(organization=owner_org, membership=owner_membership)

        assert permission_granted(db, tenant_context=admin_context, permission_key=permission_key) is False
        assert permission_granted(db, tenant_context=owner_context, permission_key=permission_key) is True


def test_custom_role_with_owner_only_key_is_not_effective() -> None:
    with SessionLocal() as db:
        _, organization, membership = _org_with_provisioned_roles(db, owner=False)
        _custom_role_with(
            db,
            organization_id=organization.id,
            permission_key="governance.capabilities.manage",
            membership=membership,
        )
        db.commit()
        context = TenantContext(organization=organization, membership=membership)

        assert permission_granted(db, tenant_context=context, permission_key="governance.capabilities.manage") is False


def test_admin_keeps_non_owner_permission_checks_working() -> None:
    with SessionLocal() as db:
        _, organization, membership = _org_with_provisioned_roles(db, owner=False)
        context = TenantContext(organization=organization, membership=membership)

        assert permission_granted(db, tenant_context=context, permission_key="governance.capabilities.read") is True


# --- API surface -------------------------------------------------------------------------------


def test_admin_cannot_change_governance_capabilities_through_the_api() -> None:
    user, organization, _ = create_admin()

    with TestClient(governance_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.patch(f"{GOVERNANCE}/{AUTOMATION_MASTER}", json={"is_enabled": True, "confirm": True})

    assert response.status_code == 403


def test_admin_can_read_governance_capabilities_through_the_api() -> None:
    user, organization, _ = create_admin()

    with TestClient(governance_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.get(GOVERNANCE)

    assert response.status_code == 200


def test_owner_can_change_governance_capabilities_through_the_api() -> None:
    user, organization, _ = create_owner()

    with TestClient(governance_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.patch(f"{GOVERNANCE}/{AUTOMATION_MASTER}", json={"is_enabled": True, "confirm": True})

    assert response.status_code == 200, response.text


def test_admin_cannot_create_provider_credentials_but_can_list_them() -> None:
    user, organization, _ = create_admin()

    with TestClient(provider_app_for(user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        created = client.post(
            PROVIDERS, json={"provider_key": "openai", "label": "x", "secret": "sk-owner-only-test"}
        )
        listed = client.get(PROVIDERS)

    assert created.status_code == 403
    assert listed.status_code == 200


# --- alternate paths: role assignment ----------------------------------------------------------


def test_custom_role_with_owner_only_key_cannot_be_assigned_to_a_member() -> None:
    with SessionLocal() as db:
        _, organization, membership = _org_with_provisioned_roles(db, owner=True)
        role = _custom_role_with(
            db,
            organization_id=organization.id,
            permission_key="governance.capabilities.manage",
            membership=membership,
        )
        db.commit()

        with pytest.raises(HTTPException) as refused:
            _get_assignable_role(db, role.id, organization_id=organization.id)

    assert refused.value.status_code == 403


def test_system_admin_role_remains_assignable() -> None:
    with SessionLocal() as db:
        _, organization, _ = _org_with_provisioned_roles(db, owner=True)
        admin_role = db.scalar(
            select(Role).where(Role.organization_id == organization.id, Role.name == "Admin")
        )
        assignable = _get_assignable_role(db, admin_role.id, organization_id=organization.id)

    assert assignable.id == admin_role.id


def test_provisioned_admin_role_holds_no_owner_only_permission_rows() -> None:
    with SessionLocal() as db:
        _, organization, _ = _org_with_provisioned_roles(db, owner=False)
        admin_role = db.scalar(
            select(Role).where(Role.organization_id == organization.id, Role.name == "Admin")
        )
        granted = set(
            db.scalars(
                select(Permission.key)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == admin_role.id)
            ).all()
        )

    assert granted.isdisjoint(OWNER_ONLY_PERMISSION_KEYS)
    assert set(READ_GOVERNANCE_KEYS) <= granted


def test_alert_recipients_require_the_owner_role_not_just_the_permission() -> None:
    from app.governance.alert_delivery import administrator_user_ids

    with SessionLocal() as db:
        _, organization, _ = _org_with_provisioned_roles(db, owner=True)
        # Same organization: a real Owner, and a non-owner whose custom role carries a budget key.
        owner_person = create_user(db)
        owner_membership = create_membership(db, user=owner_person, organization=organization)
        attach_role(
            db,
            membership=owner_membership,
            role=db.scalar(select(Role).where(Role.organization_id == organization.id, Role.name == OWNER_ROLE_NAME)),
        )
        drift_person = create_user(db)
        drift_membership = create_membership(db, user=drift_person, organization=organization)
        _custom_role_with(
            db,
            organization_id=organization.id,
            permission_key="governance.budgets.manage",
            membership=drift_membership,
        )
        db.commit()
        owner_id, drift_id, org_id = owner_person.id, drift_person.id, organization.id
        recipients = administrator_user_ids(db, organization_id=org_id)

    assert owner_id in recipients
    assert drift_id not in recipients


def test_custom_role_cannot_take_the_reserved_owner_name() -> None:
    from fastapi import HTTPException

    from app.team.service import create_organization_role

    with SessionLocal() as db:
        _, organization, _ = _org_with_provisioned_roles(db, owner=True)
        with pytest.raises(HTTPException) as refused:
            create_organization_role(
                db,
                organization_id=organization.id,
                name="dealflow owner",
                description=None,
                permission_keys=["deals.read"],
            )
        db.rollback()

    assert refused.value.status_code == 403  # the existing owner-name guard


def test_provisioning_refuses_to_promote_a_custom_role_named_owner() -> None:
    from fastapi import HTTPException

    with SessionLocal() as db:
        person = create_user(db)
        organization = create_organization(db)
        create_membership(db, user=person, organization=organization)
        squatter = Role(
            name=OWNER_ROLE_NAME,
            organization_id=organization.id,
            is_system=False,
            is_active=True,
        )
        db.add(squatter)
        db.commit()

        with pytest.raises(HTTPException) as refused:
            provision_default_organization_roles(db, organization_id=organization.id)
        db.rollback()
        still_custom = db.get(Role, squatter.id)
        assert still_custom.is_system is False

    assert refused.value.status_code == 409
