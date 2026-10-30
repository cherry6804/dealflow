"""Team membership, invitation, and organization role API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.auth.email_outbox import enqueue_team_invitation_email
from app.authz.dependencies import require_permission
from app.db.models.membership import Membership
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_db_session
from app.config import get_settings
from app.team.member_removal import SibvoActor, remove_member_and_release_seat
from app.team.schemas import (
    PermissionCatalogueItem,
    TeamInvitationAcceptRequest,
    TeamInvitationAcceptResponse,
    TeamInvitationCreateRequest,
    TeamInvitationResponse,
    TeamMemberRemovalRequest,
    TeamMemberRemovalResponse,
    TeamMemberResponse,
    TeamMemberRoleUpdateRequest,
    TeamRoleCreateRequest,
    TeamRoleResponse,
    TeamRoleUpdateRequest,
)
from app.team.service import (
    CUSTOM_ROLE_FORBIDDEN_PERMISSION_KEYS,
    InvitationExpiredError,
    accept_team_invitation,
    create_organization_role,
    create_team_invitation,
    deactivate_organization_role,
    get_role_permission_keys,
    list_organization_roles,
    list_team_invitations,
    list_team_members,
    resend_team_invitation,
    revoke_team_invitation,
    update_organization_role,
    update_team_member_role,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/team", tags=["team"])


def _role_response(db: Session, role: Role) -> TeamRoleResponse:
    return TeamRoleResponse(
        id=role.id,
        name=role.name,
        organization_id=role.organization_id,
        description=role.description,
        is_system=role.is_system,
        is_active=role.is_active,
        permission_keys=get_role_permission_keys(db, role_id=role.id),
    )


def _team_member_response(membership: Membership) -> TeamMemberResponse:
    return TeamMemberResponse(
        user_id=membership.user.id,
        display_name=membership.user.display_name,
        email=membership.user.email,
        membership_id=membership.id,
        roles=[
            TeamRoleResponse(
                id=assignment.role.id,
                name=assignment.role.name,
                organization_id=assignment.role.organization_id,
                description=assignment.role.description,
                is_system=assignment.role.is_system,
                is_active=assignment.role.is_active,
                permission_keys=[],
            )
            for assignment in membership.membership_roles
            if assignment.role is not None and assignment.role.is_active
        ],
        joined_at=membership.created_at,
    )


def _commit_or_rollback(db: Session, operation):
    """Commit a successful operation and roll back unexpected failures."""
    try:
        result = operation()
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get("/members", response_model=list[TeamMemberResponse])
def get_team_members(
    tenant: TenantContext = Depends(
        require_permission("organization.members.read")
    ),
    db: Session = Depends(get_db_session),
) -> list[TeamMemberResponse]:
    return [
        _team_member_response(member)
        for member in list_team_members(
            db,
            organization_id=tenant.organization_id,
        )
    ]


@router.get("/roles", response_model=list[TeamRoleResponse])
def get_assignable_team_roles(
    tenant: TenantContext = Depends(
        require_permission("organization.invites.manage")
    ),
    db: Session = Depends(get_db_session),
) -> list[TeamRoleResponse]:
    """List assignable roles for invitation and member-role forms."""
    from app.team.service import _get_assignable_role

    result: list[TeamRoleResponse] = []
    roles = list_organization_roles(
        db,
        organization_id=tenant.organization_id,
        include_inactive=False,
    )

    for role in roles:
        try:
            _get_assignable_role(
                db,
                role.id,
                organization_id=tenant.organization_id,
            )
        except HTTPException:
            continue
        result.append(_role_response(db, role))

    return result


@router.get("/roles/manage", response_model=list[TeamRoleResponse])
def get_organization_roles(
    tenant: TenantContext = Depends(
        require_permission("organization.roles.manage")
    ),
    db: Session = Depends(get_db_session),
) -> list[TeamRoleResponse]:
    """List all organization roles, including protected defaults."""
    roles = list_organization_roles(
        db,
        organization_id=tenant.organization_id,
        include_inactive=True,
    )
    return [_role_response(db, role) for role in roles]


@router.get("/permissions", response_model=list[PermissionCatalogueItem])
def get_permission_catalogue(
    _tenant: TenantContext = Depends(
        require_permission("organization.roles.manage")
    ),
    db: Session = Depends(get_db_session),
) -> list[PermissionCatalogueItem]:
    """Return active permissions for the role editor."""
    permissions = db.scalars(
        select(Permission)
        .where(Permission.is_active.is_(True))
        .order_by(Permission.key.asc())
    ).all()

    return [
        PermissionCatalogueItem(
            key=permission.key,
            description=permission.description,
            group=permission.key.split(".", maxsplit=1)[0],
            assignable=permission.key
            not in CUSTOM_ROLE_FORBIDDEN_PERMISSION_KEYS,
        )
        for permission in permissions
    ]


@router.post(
    "/roles",
    response_model=TeamRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_organization_role(
    payload: TeamRoleCreateRequest,
    tenant: TenantContext = Depends(
        require_permission("organization.roles.manage")
    ),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> TeamRoleResponse:
    try:
        role = create_organization_role(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=current_user.user_id,
            name=payload.name,
            description=payload.description,
            permission_keys=payload.permission_keys,
        )
        db.commit()
        db.refresh(role)
        return _role_response(db, role)
    except Exception:
        db.rollback()
        raise


@router.put("/roles/{role_id}", response_model=TeamRoleResponse)
def put_organization_role(
    role_id: UUID,
    payload: TeamRoleUpdateRequest,
    tenant: TenantContext = Depends(
        require_permission("organization.roles.manage")
    ),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> TeamRoleResponse:
    try:
        role = update_organization_role(
            db,
            organization_id=tenant.organization_id,
            role_id=role_id,
            actor_user_id=current_user.user_id,
            name=payload.name,
            description=payload.description,
            permission_keys=payload.permission_keys,
        )
        db.commit()
        db.refresh(role)
        return _role_response(db, role)
    except Exception:
        db.rollback()
        raise


@router.post("/roles/{role_id}/deactivate", response_model=TeamRoleResponse)
def post_deactivate_organization_role(
    role_id: UUID,
    tenant: TenantContext = Depends(
        require_permission("organization.roles.manage")
    ),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> TeamRoleResponse:
    try:
        role = deactivate_organization_role(
            db,
            organization_id=tenant.organization_id,
            role_id=role_id,
            actor_user_id=current_user.user_id,
        )
        db.commit()
        db.refresh(role)
        return _role_response(db, role)
    except Exception:
        db.rollback()
        raise


@router.get("/invitations", response_model=list[TeamInvitationResponse])
def get_team_invitations(
    tenant: TenantContext = Depends(
        require_permission("organization.invites.manage")
    ),
    db: Session = Depends(get_db_session),
) -> list[TeamInvitationResponse]:
    return list_team_invitations(
        db,
        organization_id=tenant.organization_id,
    )


@router.post(
    "/invitations",
    response_model=TeamInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_team_invitation(
    payload: TeamInvitationCreateRequest,
    tenant: TenantContext = Depends(
        require_permission("organization.invites.manage")
    ),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> TeamInvitationResponse:
    """Create an invitation and queue its email in the same transaction."""
    try:
        invitation, raw_token = create_team_invitation(
            db,
            organization_id=tenant.organization_id,
            invited_by_user_id=current_user.user_id,
            email=str(payload.email),
            role_id=payload.role_id,
        )

        # The outbox API expects recipient and token, not invitation/raw_token.
        enqueue_team_invitation_email(
            db,
            recipient=invitation.email,
            token=raw_token,
        )

        db.commit()
        db.refresh(invitation)
        return TeamInvitationResponse.model_validate(invitation)
    except Exception:
        db.rollback()
        raise


@router.post(
    "/invitations/accept",
    response_model=TeamInvitationAcceptResponse,
)
def post_accept_team_invitation(
    payload: TeamInvitationAcceptRequest,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> TeamInvitationAcceptResponse:
    try:
        user = db.scalar(select(User).where(User.id == current_user.user_id))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated user not found.",
            )

        invitation, membership = accept_team_invitation(
            db,
            raw_token=payload.token,
            user=user,
        )
        db.commit()

        return TeamInvitationAcceptResponse(
            organization_id=invitation.organization_id,
            membership_id=membership.id,
            message="Invitation accepted.",
        )
    except InvitationExpiredError:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has expired.",
        )
    except Exception:
        db.rollback()
        raise


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=TeamInvitationResponse,
)
def post_resend_team_invitation(
    invitation_id: UUID,
    tenant: TenantContext = Depends(
        require_permission("organization.invites.manage")
    ),
    db: Session = Depends(get_db_session),
) -> TeamInvitationResponse:
    """Rotate an invitation token and queue the replacement email."""
    try:
        invitation, raw_token = resend_team_invitation(
            db,
            invitation_id=invitation_id,
            organization_id=tenant.organization_id,
        )

        enqueue_team_invitation_email(
            db,
            recipient=invitation.email,
            token=raw_token,
        )

        db.commit()
        db.refresh(invitation)
        return TeamInvitationResponse.model_validate(invitation)
    except InvitationExpiredError:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has expired.",
        )
    except Exception:
        db.rollback()
        raise


@router.post(
    "/invitations/{invitation_id}/revoke",
    response_model=TeamInvitationResponse,
)
def post_revoke_team_invitation(
    invitation_id: UUID,
    tenant: TenantContext = Depends(
        require_permission("organization.invites.manage")
    ),
    db: Session = Depends(get_db_session),
) -> TeamInvitationResponse:
    try:
        invitation = revoke_team_invitation(
            db,
            invitation_id=invitation_id,
            organization_id=tenant.organization_id,
        )
        db.commit()
        db.refresh(invitation)
        return TeamInvitationResponse.model_validate(invitation)
    except Exception:
        db.rollback()
        raise


@router.put(
    "/members/{membership_id}/role",
    response_model=TeamMemberResponse,
)
def put_team_member_role(
    membership_id: UUID,
    payload: TeamMemberRoleUpdateRequest,
    tenant: TenantContext = Depends(
        require_permission("organization.members.manage")
    ),
    db: Session = Depends(get_db_session),
) -> TeamMemberResponse:
    try:
        membership = update_team_member_role(
            db,
            organization_id=tenant.organization_id,
            membership_id=membership_id,
            role_id=payload.role_id,
        )
        db.commit()
        db.refresh(membership)
        return _team_member_response(membership)
    except Exception:
        db.rollback()
        raise


@router.post(
    "/members/{membership_id}/remove",
    response_model=TeamMemberRemovalResponse,
)
def post_remove_team_member(
    membership_id: UUID,
    payload: TeamMemberRemovalRequest | None = None,
    tenant: TenantContext = Depends(
        require_permission("organization.members.manage")
    ),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> TeamMemberRemovalResponse:
    """Remove a team member and release their SIBVO product seat.

    The removal is reported only after SIBVO confirms the seat outcome. When SIBVO
    does not confirm, the member stays active and the request fails with 503.
    """
    try:
        outcome = remove_member_and_release_seat(
            db,
            settings=get_settings(),
            organization_id=tenant.organization_id,
            membership_id=membership_id,
            actor_user_id=current_user.user_id,
            actor=SibvoActor(
                subject=current_user.sibvo_subject,
                session_id=current_user.sibvo_session_id,
                organization_id=current_user.sibvo_organization_id,
            ),
            reason=(payload.reason if payload else "").strip(),
        )
        db.commit()
        return TeamMemberRemovalResponse(
            membership_id=outcome.membership_id,
            is_active=outcome.is_active,
            seat_outcome=outcome.seat_outcome,
            already_removed=outcome.already_removed,
            message=(
                "Member was already removed. SIBVO confirmed the seat."
                if outcome.already_removed
                else "Member removed. SIBVO confirmed the seat."
            ),
        )
    except Exception:
        db.rollback()
        raise
