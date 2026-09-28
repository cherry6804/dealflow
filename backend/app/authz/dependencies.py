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
    """
    Create a FastAPI dependency that requires a specific permission.

    Authorization is evaluated server-side from the verified tenant
    membership and its assigned roles and permissions.

    The client cannot provide or override roles or permissions.

    Successful and denied authorization decisions are recorded through
    an independent audit transaction.
    """

    normalized_permission_key = permission_key.strip()

    if not normalized_permission_key:
        raise ValueError("Permission key cannot be empty.")

    def permission_dependency(
        tenant_context: TenantContext = Depends(get_tenant_context),
        db: Session = Depends(get_db_session),
    ) -> TenantContext:
        """Require the configured permission for the current tenant."""

        statement = (
            select(Permission.id)
            .join(
                RolePermission,
                RolePermission.permission_id == Permission.id,
            )
            .join(
                Role,
                Role.id == RolePermission.role_id,
            )
            .join(
                MembershipRole,
                MembershipRole.role_id == Role.id,
            )
            .where(
                MembershipRole.membership_id == tenant_context.membership.id,
                Permission.key == normalized_permission_key,
                Permission.is_active.is_(True),
                Role.is_active.is_(True),
            )
            .limit(1)
        )

        permission_id = db.scalar(statement)

        if permission_id is None:
            persist_authorization_audit_event(
                user_id=tenant_context.membership.user_id,
                organization_id=tenant_context.organization_id,
                action=normalized_permission_key,
                decision=AuditDecision.DENIED,
                permission_key=normalized_permission_key,
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied.",
            )

        persist_authorization_audit_event(
            user_id=tenant_context.membership.user_id,
            organization_id=tenant_context.organization_id,
            action=normalized_permission_key,
            decision=AuditDecision.ALLOWED,
            permission_key=normalized_permission_key,
        )

        return tenant_context

    return permission_dependency