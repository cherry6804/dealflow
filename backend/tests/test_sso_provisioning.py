from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.sso import _provision_sso_access
from app.db.models.audit_event import AuditEvent
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.role import Role
from app.db.models.sibvo_identity_link import SibvoIdentityLink
from app.db.models.sibvo_organization_link import SibvoOrganizationLink
from app.db.models.user import User
from app.db.session import engine
from app.team.service import (
    create_team_invitation,
    provision_default_organization_roles,
)


@pytest.fixture
def provisioning_db():
    """Use a transaction on the isolated PostgreSQL test database."""
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection)
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


def prepare_invitation(db: Session, email: str) -> tuple[Organization, User, str]:
    owner = User(
        email=f"owner-{uuid4()}@example.com",
        display_name="Workspace Owner",
        password_hash="not-used-by-sso",
        is_active=True,
        is_email_verified=True,
    )
    organization = Organization(name="Invited Workspace", is_active=True)
    db.add_all([owner, organization])
    db.flush()
    roles = {
        role.name: role
        for role in db.scalars(
            select(Role).where(Role.organization_id == organization.id)
        ).all()
    }
    if not roles:
        provision_default_organization_roles(db, organization_id=organization.id)
        roles = {
            role.name: role
            for role in db.scalars(
                select(Role).where(Role.organization_id == organization.id)
            ).all()
        }
    _invitation, raw_token = create_team_invitation(
        db,
        organization_id=organization.id,
        invited_by_user_id=owner.id,
        email=email,
        role_id=next(role.id for role in roles.values() if role.name == "Member"),
        now=datetime.now(UTC),
    )
    db.add(
        SibvoOrganizationLink(
            sibvo_organization_id=uuid4(),
            dealsflo_organization_id=organization.id,
        )
    )
    db.flush()
    return organization, owner, raw_token


def test_invitation_provisions_and_idempotently_links_sibvo_user(
    provisioning_db: Session,
) -> None:
    db = provisioning_db
    email = f"invitee-{uuid4()}@example.com"
    organization, _, raw_token = prepare_invitation(db, email)
    sibvo_org_id = db.scalar(
        select(SibvoOrganizationLink.sibvo_organization_id).where(
            SibvoOrganizationLink.dealsflo_organization_id == organization.id
        )
    )
    subject = uuid4()
    params = {
        "subject": subject,
        "sibvo_organization_id": sibvo_org_id,
        "email": email,
        "display_name": "Invited User",
        "organization_name": "Ignored for existing mapping",
        "organization_role": "member",
        "invitation_token": raw_token,
    }

    first_user, first_organization = _provision_sso_access(db, **params)
    db.flush()
    second_user, second_organization = _provision_sso_access(db, **params)

    assert first_user.id == second_user.id
    assert first_organization.id == second_organization.id == organization.id
    assert (
        db.scalar(
            select(SibvoIdentityLink).where(SibvoIdentityLink.sibvo_subject == subject)
        ).dealsflo_user_id
        == first_user.id
    )
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == first_user.id,
            Membership.organization_id == organization.id,
        )
    )
    assert membership is not None and membership.is_active
    assigned_roles = db.scalars(
        select(Role.name)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(MembershipRole.membership_id == membership.id)
    ).all()
    assert assigned_roles == ["Member"]
    audit_actions = db.scalars(
        select(AuditEvent.action).where(AuditEvent.user_id == first_user.id)
    ).all()
    assert "sso.identity_link.created" in audit_actions
    assert "sso.invitation.accepted" in audit_actions


def test_invitation_cannot_link_a_different_verified_email(
    provisioning_db: Session,
) -> None:
    db = provisioning_db
    invited_email = f"invited-{uuid4()}@example.com"
    organization, _, raw_token = prepare_invitation(db, invited_email)
    sibvo_org_id = db.scalar(
        select(SibvoOrganizationLink.sibvo_organization_id).where(
            SibvoOrganizationLink.dealsflo_organization_id == organization.id
        )
    )
    subject = uuid4()

    with pytest.raises(HTTPException) as error:
        _provision_sso_access(
            db,
            subject=subject,
            sibvo_organization_id=sibvo_org_id,
            email=f"attacker-{uuid4()}@example.com",
            display_name="Wrong User",
            organization_name="Invited Workspace",
            organization_role="member",
            invitation_token=raw_token,
        )

    assert error.value.status_code == 403
    assert (
        db.scalar(
            select(SibvoIdentityLink).where(SibvoIdentityLink.sibvo_subject == subject)
        )
        is None
    )
    assert db.scalar(select(User).where(User.email == invited_email)) is None


def test_entitled_sibvo_owner_bootstraps_workspace_once(
    provisioning_db: Session,
) -> None:
    db = provisioning_db
    subject = uuid4()
    sibvo_org_id = uuid4()
    email = f"owner-{uuid4()}@example.com"
    params = {
        "subject": subject,
        "sibvo_organization_id": sibvo_org_id,
        "email": email,
        "display_name": "SIBVO Owner",
        "organization_name": "New Dealsflo Workspace",
        "organization_role": "owner",
        "invitation_token": None,
    }

    user, organization = _provision_sso_access(db, **params)
    db.flush()
    retry_user, retry_organization = _provision_sso_access(db, **params)

    assert retry_user.id == user.id
    assert retry_organization.id == organization.id
    assert organization.name == "New Dealsflo Workspace"
    assert (
        db.scalar(
            select(SibvoOrganizationLink).where(
                SibvoOrganizationLink.sibvo_organization_id == sibvo_org_id
            )
        ).dealsflo_organization_id
        == organization.id
    )
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == organization.id,
        )
    )
    assert membership is not None and membership.is_active
    role_names = db.scalars(
        select(Role.name)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(MembershipRole.membership_id == membership.id)
    ).all()
    assert role_names == ["DealFlow Owner"]
    assert (
        db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "sso.organization.provisioned",
                AuditEvent.organization_id == organization.id,
            )
        )
        is not None
    )


def test_existing_account_with_same_email_is_not_linked_without_invitation(
    provisioning_db: Session,
) -> None:
    """Matching email alone never links an existing local account to a SIBVO subject."""
    db = provisioning_db
    email = f"existing-{uuid4()}@example.com"
    existing = User(
        email=email,
        display_name="Existing Member",
        password_hash="not-used-by-sso",
        is_active=True,
        is_email_verified=True,
    )
    db.add(existing)
    db.flush()
    subject = uuid4()

    with pytest.raises(HTTPException) as denied:
        _provision_sso_access(
            db,
            subject=subject,
            sibvo_organization_id=uuid4(),
            email=email,
            display_name="Existing Member",
            organization_name="Attempted Workspace",
            organization_role="owner",
            invitation_token=None,
        )

    assert denied.value.status_code == 403
    assert (
        db.scalar(
            select(SibvoIdentityLink).where(SibvoIdentityLink.sibvo_subject == subject)
        )
        is None
    )
    assert db.scalar(select(Membership).where(Membership.user_id == existing.id)) is None
