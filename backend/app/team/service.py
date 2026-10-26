"""Secure team invitation, membership, and organization role services."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.audit.service import create_authorization_audit_event
from app.db.models.audit_event import AuditDecision
from app.authz.permissions import OWNER_ROLE_PERMISSION_KEYS, PERMISSION_CATALOG
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.team_invitation import TeamInvitation
from app.db.models.user import User


INVITATION_LIFETIME = timedelta(days=7)
OWNER_ROLE_NAME = "DealFlow Owner"
ROLE_ADMIN_PERMISSION = "organization.roles.manage"
CUSTOM_ROLE_FORBIDDEN_PERMISSION_KEYS = frozenset(
    {
        "organization.roles.manage",
        "billing.audit.read",
        "organization.members.manage",
        "organization.invites.manage",
    }
)


def _audit_role_change(
    db: Session,
    *,
    actor_user_id: UUID | None,
    organization_id: UUID,
    role_id: UUID,
    action: str,
) -> None:
    """Record role administration in the same transaction as the change."""
    if actor_user_id is None:
        return

    create_authorization_audit_event(
        db,
        user_id=actor_user_id,
        organization_id=organization_id,
        action=action,
        decision=AuditDecision.ALLOWED,
        permission_key=ROLE_ADMIN_PERMISSION,
        resource_type="role",
        resource_id=str(role_id),
    )

DEFAULT_ROLE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "DealFlow Owner": OWNER_ROLE_PERMISSION_KEYS,
    "Admin": tuple(
        key for key, _ in PERMISSION_CATALOG
        if key not in {"organization.roles.manage", "billing.audit.read"}
    ),
    "Manager": (
        "contacts.create", "contacts.read", "contacts.update",
        "leads.create", "leads.read", "leads.update",
        "properties.create", "properties.read", "properties.update",
        "requirements.create", "requirements.read", "requirements.update",
        "deals.create", "deals.read", "deals.update",
        "deal_negotiations.read", "deal_negotiations.update",
        "payment_milestones.read", "payment_milestones.create",
        "payment_milestones.update", "commission.read",
        "commission.create", "commission.update", "referrals.read",
        "referrals.create", "referrals.update", "documents.read",
        "documents.upload", "documents.download", "automation.read",
        "automation.create", "automation.update", "organization.members.read",
    ),
    "Member": (
        "contacts.create", "contacts.read", "contacts.update",
        "leads.create", "leads.read", "leads.update",
        "properties.create", "properties.read", "properties.update",
        "requirements.create", "requirements.read", "requirements.update",
        "deals.create", "deals.read", "deals.update",
        "deal_negotiations.read", "payment_milestones.read",
        "commission.read", "referrals.read", "documents.read",
        "documents.upload", "documents.download",
        "notifications.preferences.read", "notifications.preferences.update",
    ),
    "Viewer": (
        "contacts.read", "leads.read", "properties.read",
        "requirements.read", "deals.read", "deal_negotiations.read",
        "payment_milestones.read", "commission.read", "referrals.read",
        "documents.read", "documents.download", "organization.members.read",
        "notifications.preferences.read",
    ),
}

PERMISSION_DESCRIPTIONS = dict(PERMISSION_CATALOG)
KNOWN_PERMISSION_KEYS = frozenset(PERMISSION_DESCRIPTIONS)


class InvitationExpiredError(Exception):
    """An expired invitation must be committed before returning an error."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_invitation_token(token: str) -> str:
    """Hash a raw invitation token before persistence or lookup."""
    if not token:
        raise ValueError("Invitation token cannot be empty.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def _is_owner_role(role: Role) -> bool:
    return role.name.strip().casefold() == OWNER_ROLE_NAME.casefold()


def provision_default_organization_roles(
    db: Session,
    *,
    organization_id: UUID,
) -> Role:
    """Create missing standard roles and return the organization's Owner role.

    Call this after flushing the organization, inside the signup transaction.
    """
    permission_by_key = {
        row.key: row for row in db.scalars(select(Permission)).all()
    }

    for key, description in PERMISSION_CATALOG:
        if key not in permission_by_key:
            permission = Permission(
                key=key,
                description=description,
                is_active=True,
            )
            db.add(permission)
            db.flush()
            permission_by_key[key] = permission

    descriptions = {
        "DealFlow Owner": "Full administrative access to this organization.",
        "Admin": "Manage day-to-day organization operations and team access.",
        "Manager": "Manage operational records and team workflows.",
        "Member": "Create and update standard business records.",
        "Viewer": "Read-only access to standard business records.",
    }

    roles_by_name: dict[str, Role] = {}

    for role_name, permission_keys in DEFAULT_ROLE_TEMPLATES.items():
        role = db.scalar(
            select(Role).where(
                Role.organization_id == organization_id,
                func.lower(Role.name) == role_name.casefold(),
            )
        )

        if role is None:
            role = Role(
                organization_id=organization_id,
                name=role_name,
                description=descriptions[role_name],
                is_system=True,
                is_active=True,
            )
            db.add(role)
            db.flush()
        else:
            role.is_system = True
            role.is_active = True

        roles_by_name[role_name] = role

        existing_permission_ids = set(
            db.scalars(
                select(RolePermission.permission_id).where(
                    RolePermission.role_id == role.id
                )
            ).all()
        )

        for key in permission_keys:
            permission = permission_by_key.get(key)
            if (
                permission is not None
                and permission.is_active
                and permission.id not in existing_permission_ids
            ):
                db.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )
                existing_permission_ids.add(permission.id)

    db.flush()
    return roles_by_name[OWNER_ROLE_NAME]


def _get_assignable_role(
    db: Session,
    role_id: UUID,
    *,
    organization_id: UUID,
) -> Role:
    """Find an active role belonging to this organization and safe to assign."""
    role = db.scalar(
        select(Role).where(
            Role.id == role_id,
            Role.organization_id == organization_id,
            Role.is_active.is_(True),
        )
    )

    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested role was not found in this organization.",
        )

    if _is_owner_role(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The owner role cannot be assigned through team management.",
        )

    permission_keys = set(
        db.scalars(
            select(Permission.key)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(
                RolePermission.role_id == role.id,
                Permission.is_active.is_(True),
            )
        ).all()
    )

    owner_only_permissions = permission_keys & {
        "organization.roles.manage",
        "billing.audit.read",
    }
    forbidden_custom_permissions = (
        not role.is_system
        and bool(permission_keys & CUSTOM_ROLE_FORBIDDEN_PERMISSION_KEYS)
    )
    if owner_only_permissions or forbidden_custom_permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Roles with Owner-only permissions cannot be assigned.",
        )

    return role


def _get_organization_role(
    db: Session,
    *,
    organization_id: UUID,
    role_id: UUID,
    lock: bool = False,
) -> Role:
    statement = select(Role).where(
        Role.id == role_id,
        Role.organization_id == organization_id,
    )
    if lock:
        statement = statement.with_for_update()

    role = db.scalar(statement)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found in this organization.",
        )
    return role


def _validate_permission_keys(
    permission_keys: list[str] | tuple[str, ...],
) -> set[str]:
    requested = {key.strip() for key in permission_keys if key.strip()}
    unknown = requested - KNOWN_PERMISSION_KEYS

    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "One or more permission keys are not supported.",
                "unknown_permissions": sorted(unknown),
            },
        )

    forbidden = requested & CUSTOM_ROLE_FORBIDDEN_PERMISSION_KEYS
    if forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Custom roles cannot grant Owner-only permissions.",
                "forbidden_permissions": sorted(forbidden),
            },
        )

    return requested


def _ensure_permission_rows(
    db: Session,
    permission_keys: set[str],
) -> dict[str, Permission]:
    """Resolve active permission records without trusting client-supplied IDs."""
    rows = (
        db.scalars(
            select(Permission).where(
                Permission.key.in_(permission_keys),
                Permission.is_active.is_(True),
            )
        ).all()
        if permission_keys
        else []
    )

    by_key = {row.key: row for row in rows}
    missing = permission_keys - set(by_key)

    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Some permissions are not seeded in the database yet.",
                "missing_permissions": sorted(missing),
            },
        )

    return by_key


def _replace_role_permissions(
    db: Session,
    *,
    role: Role,
    permission_keys: set[str],
) -> None:
    permission_rows = _ensure_permission_rows(db, permission_keys)

    db.query(RolePermission).filter(
        RolePermission.role_id == role.id
    ).delete(synchronize_session=False)

    for key in sorted(permission_keys):
        db.add(
            RolePermission(
                role_id=role.id,
                permission_id=permission_rows[key].id,
            )
        )

    db.flush()


def list_organization_roles(
    db: Session,
    *,
    organization_id: UUID,
    include_inactive: bool = False,
) -> list[Role]:
    statement = select(Role).where(Role.organization_id == organization_id)
    if not include_inactive:
        statement = statement.where(Role.is_active.is_(True))

    return list(db.scalars(statement.order_by(Role.name.asc())).all())


def get_role_permission_keys(db: Session, role_id: UUID) -> list[str]:
    return sorted(
        db.scalars(
            select(Permission.key)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(
                RolePermission.role_id == role_id,
                Permission.is_active.is_(True),
            )
        ).all()
    )


def create_organization_role(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID | None = None,
    name: str,
    description: str | None,
    permission_keys: list[str],
) -> Role:
    normalized_name = " ".join(name.split())

    if len(normalized_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role name must contain at least two characters.",
        )

    if normalized_name.casefold() == OWNER_ROLE_NAME.casefold():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The organization owner role cannot be recreated as a custom role.",
        )

    organization = db.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")

    duplicate = db.scalar(
        select(Role.id).where(
            Role.organization_id == organization_id,
            func.lower(Role.name) == normalized_name.casefold(),
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A role with this name already exists in this organization.",
        )

    keys = _validate_permission_keys(permission_keys)
    role = Role(
        organization_id=organization_id,
        name=normalized_name,
        description=description.strip() if description else None,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    _replace_role_permissions(db, role=role, permission_keys=keys)
    _audit_role_change(
        db,
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        role_id=role.id,
        action="organization.roles.created",
    )
    return role


def update_organization_role(
    db: Session,
    *,
    organization_id: UUID,
    role_id: UUID,
    actor_user_id: UUID | None = None,
    name: str | None = None,
    description: str | None = None,
    permission_keys: list[str] | None = None,
) -> Role:
    role = _get_organization_role(
        db,
        organization_id=organization_id,
        role_id=role_id,
        lock=True,
    )

    if role.is_system or _is_owner_role(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System and owner roles cannot be edited.",
        )

    if not role.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inactive roles cannot be edited.",
        )

    if name is not None:
        normalized_name = " ".join(name.split())
        if len(normalized_name) < 2:
            raise HTTPException(status_code=422, detail="Role name must contain at least two characters.")
        if normalized_name.casefold() == OWNER_ROLE_NAME.casefold():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A custom role cannot be renamed to the owner role.",
            )

        duplicate = db.scalar(
            select(Role.id).where(
                Role.organization_id == organization_id,
                func.lower(Role.name) == normalized_name.casefold(),
                Role.id != role.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A role with this name already exists in this organization.",
            )

        role.name = normalized_name

    if description is not None:
        role.description = description.strip() or None

    if permission_keys is not None:
        _replace_role_permissions(
            db,
            role=role,
            permission_keys=_validate_permission_keys(permission_keys),
        )

    db.flush()
    _audit_role_change(
        db,
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        role_id=role.id,
        action="organization.roles.updated",
    )
    return role

def deactivate_organization_role(
    db: Session,
    *,
    organization_id: UUID,
    role_id: UUID,
    actor_user_id: UUID | None = None,
) -> Role:
    role = _get_organization_role(
        db,
        organization_id=organization_id,
        role_id=role_id,
        lock=True,
    )

    if role.is_system or _is_owner_role(role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System and owner roles cannot be deactivated.",
        )

    if not role.is_active:
        return role

    assigned_count = db.scalar(
        select(func.count(MembershipRole.id))
        .join(Membership, Membership.id == MembershipRole.membership_id)
        .where(
            Membership.organization_id == organization_id,
            Membership.is_active.is_(True),
            MembershipRole.role_id == role.id,
        )
    ) or 0

    pending_count = db.scalar(
        select(func.count(TeamInvitation.id)).where(
            TeamInvitation.organization_id == organization_id,
            TeamInvitation.role_id == role.id,
            TeamInvitation.status == "pending",
        )
    ) or 0

    if assigned_count or pending_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Reassign members and resolve pending invitations before "
                "deactivating this role."
            ),
        )

    role.is_active = False
    db.flush()
    _audit_role_change(
        db,
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        role_id=role.id,
        action="organization.roles.deactivated",
    )
    return role


def _get_organization_membership(
    db: Session,
    *,
    organization_id: UUID,
    membership_id: UUID,
    lock: bool = False,
) -> Membership:
    statement = (
        select(Membership)
        .options(
            joinedload(Membership.user),
            joinedload(Membership.membership_roles).joinedload(MembershipRole.role),
        )
        .where(
            Membership.id == membership_id,
            Membership.organization_id == organization_id,
        )
    )

    if lock:
        statement = statement.with_for_update(of=Membership)

    membership = db.scalars(statement).unique().one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found.",
        )

    return membership


def _is_owner_membership(membership: Membership) -> bool:
    return any(
        assignment.role is not None and _is_owner_role(assignment.role)
        for assignment in membership.membership_roles
    )


def _active_owner_count(db: Session, organization_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.count(func.distinct(Membership.id)))
            .join(MembershipRole, MembershipRole.membership_id == Membership.id)
            .join(Role, Role.id == MembershipRole.role_id)
            .where(
                Membership.organization_id == organization_id,
                Membership.is_active.is_(True),
                Role.is_active.is_(True),
                Role.organization_id == organization_id,
                func.lower(func.trim(Role.name)) == OWNER_ROLE_NAME.casefold(),
            )
        ) or 0
    )


def list_team_members(
    db: Session,
    *,
    organization_id: UUID,
) -> list[Membership]:
    return list(
        db.scalars(
            select(Membership)
            .options(
                joinedload(Membership.user),
                joinedload(Membership.membership_roles).joinedload(MembershipRole.role),
            )
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == organization_id,
                Membership.is_active.is_(True),
                User.is_active.is_(True),
            )
            .order_by(User.display_name.asc(), User.email.asc())
        ).unique().all()
    )


def list_team_invitations(
    db: Session,
    *,
    organization_id: UUID,
) -> list[TeamInvitation]:
    return list(
        db.scalars(
            select(TeamInvitation)
            .where(TeamInvitation.organization_id == organization_id)
            .order_by(TeamInvitation.created_at.desc())
        ).all()
    )


def create_team_invitation(
    db: Session,
    *,
    organization_id: UUID,
    invited_by_user_id: UUID,
    email: str,
    role_id: UUID,
    now: datetime | None = None,
) -> tuple[TeamInvitation, str]:
    current_time = now or _utc_now()
    normalized_email = email.strip().casefold()

    if not normalized_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid email address is required.",
        )

    organization = db.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.is_active.is_(True),
        )
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")

    _get_assignable_role(db, role_id, organization_id=organization_id)

    existing_user = db.scalar(
        select(User).where(func.lower(User.email) == normalized_email)
    )
    if existing_user is not None:
        existing_membership = db.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == existing_user.id,
            )
        )
        if existing_membership is not None and existing_membership.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user is already a member of the organization.",
            )

    pending_invitations = db.scalars(
        select(TeamInvitation)
        .where(
            TeamInvitation.organization_id == organization_id,
            func.lower(TeamInvitation.email) == normalized_email,
            TeamInvitation.status == "pending",
        )
        .with_for_update()
    ).all()

    for pending in pending_invitations:
        if _as_utc(pending.expires_at) > _as_utc(current_time):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A pending invitation already exists for this email address.",
            )
        pending.status = "expired"

    raw_token = _generate_invitation_token()
    invitation = TeamInvitation(
        organization_id=organization_id,
        email=normalized_email,
        role_id=role_id,
        token_hash=hash_invitation_token(raw_token),
        status="pending",
        invited_by_user_id=invited_by_user_id,
        created_at=current_time,
        expires_at=current_time + INVITATION_LIFETIME,
    )
    db.add(invitation)
    db.flush()
    return invitation, raw_token


def resend_team_invitation(
    db: Session,
    *,
    organization_id: UUID,
    invitation_id: UUID,
    now: datetime | None = None,
) -> tuple[TeamInvitation, str]:
    current_time = now or _utc_now()
    invitation = db.scalar(
        select(TeamInvitation)
        .where(
            TeamInvitation.id == invitation_id,
            TeamInvitation.organization_id == organization_id,
        )
        .with_for_update()
    )

    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")

    if invitation.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Only pending invitations can be resent.",
        )

    if _as_utc(invitation.expires_at) <= _as_utc(current_time):
        invitation.status = "expired"
        db.flush()
        raise InvitationExpiredError

    _get_assignable_role(
        db,
        invitation.role_id,
        organization_id=invitation.organization_id,
    )

    raw_token = _generate_invitation_token()
    invitation.token_hash = hash_invitation_token(raw_token)
    invitation.expires_at = current_time + INVITATION_LIFETIME
    db.flush()
    return invitation, raw_token


def revoke_team_invitation(
    db: Session,
    *,
    organization_id: UUID,
    invitation_id: UUID,
    now: datetime | None = None,
) -> TeamInvitation:
    current_time = now or _utc_now()
    invitation = db.scalar(
        select(TeamInvitation)
        .where(
            TeamInvitation.id == invitation_id,
            TeamInvitation.organization_id == organization_id,
        )
        .with_for_update()
    )

    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")

    if invitation.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Only pending invitations can be revoked.",
        )

    invitation.status = "revoked"
    invitation.revoked_at = current_time
    db.flush()
    return invitation


def update_team_member_role(
    db: Session,
    *,
    organization_id: UUID,
    membership_id: UUID,
    role_id: UUID,
) -> Membership:
    membership = _get_organization_membership(
        db,
        organization_id=organization_id,
        membership_id=membership_id,
        lock=True,
    )

    if not membership.is_active:
        raise HTTPException(
            status_code=409,
            detail="Inactive memberships cannot be changed.",
        )

    if _is_owner_membership(membership):
        raise HTTPException(
            status_code=403,
            detail="Owner memberships cannot be modified through team management.",
        )

    role = _get_assignable_role(
        db,
        role_id,
        organization_id=organization_id,
    )

    db.query(MembershipRole).filter(
        MembershipRole.membership_id == membership.id
    ).delete(synchronize_session=False)

    db.add(MembershipRole(membership_id=membership.id, role_id=role.id))
    db.flush()
    return membership


def remove_team_member(
    db: Session,
    *,
    organization_id: UUID,
    membership_id: UUID,
    actor_user_id: UUID,
) -> Membership:
    membership = _get_organization_membership(
        db,
        organization_id=organization_id,
        membership_id=membership_id,
        lock=True,
    )

    if membership.user_id == actor_user_id:
        raise HTTPException(
            status_code=409,
            detail="You cannot remove your own membership through this endpoint.",
        )

    if not membership.is_active:
        raise HTTPException(
            status_code=409,
            detail="This membership is already inactive.",
        )

    if _is_owner_membership(membership):
        if _active_owner_count(db, organization_id) <= 1:
            raise HTTPException(
                status_code=409,
                detail="The last active organization owner cannot be removed.",
            )

        raise HTTPException(
            status_code=403,
            detail="Owner memberships cannot be removed through team management.",
        )

    membership.is_active = False
    db.flush()
    return membership


def accept_team_invitation(
    db: Session,
    *,
    raw_token: str,
    user: User,
    now: datetime | None = None,
) -> tuple[TeamInvitation, Membership]:
    current_time = now or _utc_now()

    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="An active account is required to accept an invitation.",
        )

    if not user.is_email_verified:
        raise HTTPException(
            status_code=403,
            detail="Verify your email address before accepting an invitation.",
        )

    invitation = db.scalar(
        select(TeamInvitation)
        .where(TeamInvitation.token_hash == hash_invitation_token(raw_token))
        .with_for_update()
    )

    if invitation is None:
        raise HTTPException(
            status_code=404,
            detail="Invitation is invalid or no longer available.",
        )

    if invitation.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="This invitation has already been used or revoked.",
        )

    if _as_utc(invitation.expires_at) <= _as_utc(current_time):
        invitation.status = "expired"
        db.flush()
        raise InvitationExpiredError

    if user.email.strip().casefold() != invitation.email.strip().casefold():
        raise HTTPException(
            status_code=403,
            detail="Sign in using the email address that received the invitation.",
        )

    organization = db.scalar(
        select(Organization).where(
            Organization.id == invitation.organization_id,
            Organization.is_active.is_(True),
        )
    )
    if organization is None:
        raise HTTPException(
            status_code=404,
            detail="The invited organization is no longer available.",
        )

    role = _get_assignable_role(
        db,
        invitation.role_id,
        organization_id=invitation.organization_id,
    )

    membership = db.scalar(
        select(Membership)
        .where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == user.id,
        )
        .with_for_update()
    )

    if membership is not None and membership.is_active:
        raise HTTPException(
            status_code=409,
            detail="This account is already a member of the organization.",
        )

    if membership is None:
        membership = Membership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            is_active=True,
        )
        db.add(membership)
        db.flush()
    else:
        membership.is_active = True
        db.query(MembershipRole).filter(
            MembershipRole.membership_id == membership.id
        ).delete(synchronize_session=False)

    db.add(MembershipRole(membership_id=membership.id, role_id=role.id))
    invitation.status = "accepted"
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = current_time
    db.flush()
    return invitation, membership