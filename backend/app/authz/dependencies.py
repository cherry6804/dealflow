"""Authorization dependencies for DealFlow."""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import persist_authorization_audit_event
from app.db.models.audit_event import AuditDecision
from app.db.models.membership_role import MembershipRole
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext, get_tenant_context


def require_permission(
    permission_key: str,
) -> Callable[..., TenantContext]:
    """Require a permission granted by a role in the selected tenant."""

    normalized_permission_key = permission_key.strip()
    if not normalized_permission_key:
        raise ValueError("Permission key cannot be empty.")

    def permission_dependency(
        tenant_context: TenantContext = Depends(get_tenant_context),
        db: Session = Depends(get_db_session),
    ) -> TenantContext:
        """Authorize against the selected organization's membership."""

        statement = (
            select(Permission.id)
            .join(
                RolePermission,
                RolePermission.permission_id == Permission.id,
            )
            .join(Role, Role.id == RolePermission.role_id)
            .join(MembershipRole, MembershipRole.role_id == Role.id)
            .where(
                MembershipRole.membership_id == tenant_context.membership.id,
                Role.organization_id == tenant_context.organization_id,
                Permission.key == normalized_permission_key,
                Permission.is_active.is_(True),
                Role.is_active.is_(True),
            )
            .limit(1)
        )

        permission_id = db.scalar(statement)
        decision = (
            AuditDecision.ALLOWED
            if permission_id is not None
            else AuditDecision.DENIED
        )

        persist_authorization_audit_event(
            user_id=tenant_context.membership.user_id,
            organization_id=tenant_context.organization_id,
            action=normalized_permission_key,
            decision=decision,
            permission_key=normalized_permission_key,
        )

        if permission_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied.",
            )

        return tenant_context

    return permission_dependency