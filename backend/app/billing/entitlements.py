"""Tenant-scoped subscription entitlement enforcement."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.plan import Plan
from app.db.models.plan_entitlement import PlanEntitlement
from app.db.models.subscription import Subscription
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext, get_tenant_context


ACCESSIBLE_STATUSES = {
    Subscription.STATUS_ACTIVE,
    Subscription.STATUS_TRIALING,
}


def _utc(value: datetime) -> datetime:
    """Normalize database timestamps for safe UTC comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_accessible_plan(
    db: Session,
    *,
    organization_id: UUID,
) -> Plan:
    """Return the tenant's eligible subscription plan or deny access.

    The latest subscription is treated as authoritative. If multiple
    subscriptions per organization are permitted by the data model,
    that policy should be explicitly enforced and documented.
    """
    subscription = db.scalar(
        select(Subscription)
        .where(Subscription.organization_id == organization_id)
        .order_by(
            Subscription.created_at.desc(),
            Subscription.id.desc(),
        )
        .limit(1)
    )

    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An eligible subscription is required.",
        )

    now = datetime.now(timezone.utc)

    if subscription.status not in ACCESSIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The subscription does not permit access.",
        )

    if (
        subscription.current_period_end is not None
        and _utc(subscription.current_period_end) <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The subscription period has ended.",
        )

    if (
        subscription.status == Subscription.STATUS_TRIALING
        and subscription.trial_ends_at is not None
        and _utc(subscription.trial_ends_at) <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The subscription trial has ended.",
        )

    if subscription.plan_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The subscription has no configured plan.",
        )

    plan = db.get(Plan, subscription.plan_id)

    if plan is None or not plan.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The subscription plan is unavailable.",
        )

    return plan


def get_entitlement_value(
    db: Session,
    *,
    organization_id: UUID,
    key: str,
) -> Any:
    """Resolve a configured entitlement from the tenant's current plan."""
    normalized_key = key.strip()

    if not normalized_key:
        raise ValueError("Entitlement key cannot be empty.")

    plan = get_accessible_plan(
        db,
        organization_id=organization_id,
    )

    entitlement = db.scalar(
        select(PlanEntitlement).where(
            PlanEntitlement.plan_id == plan.id,
            PlanEntitlement.key == normalized_key,
        )
    )

    if entitlement is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The required entitlement is not included in this plan.",
        )

    value = entitlement.value

    if entitlement.value_type == "BOOLEAN":
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The configured entitlement is invalid.",
            )

    elif entitlement.value_type == "INTEGER":
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The configured entitlement is invalid.",
            )

    elif entitlement.value_type == "STRING":
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The configured entitlement is invalid.",
            )

    elif entitlement.value_type != "JSON":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The configured entitlement is invalid.",
        )

    return value


def require_entitlement(
    key: str,
) -> Callable[..., TenantContext]:
    """Require a Boolean feature entitlement."""
    normalized_key = key.strip()

    if not normalized_key:
        raise ValueError("Entitlement key cannot be empty.")

    def entitlement_dependency(
        tenant_context: TenantContext = Depends(get_tenant_context),
        db: Session = Depends(get_db_session),
    ) -> TenantContext:
        value = get_entitlement_value(
            db,
            organization_id=tenant_context.organization_id,
            key=normalized_key,
        )

        if value is not True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This feature is not enabled for your subscription.",
            )

        return tenant_context

    return entitlement_dependency


def require_entitlement_with_permission(
    entitlement_key: str,
    permission_key: str,
) -> Callable[..., TenantContext]:
    """Require both an RBAC permission and a Boolean plan entitlement.

    RBAC is checked first. The entitlement check then uses the verified
    tenant returned by the RBAC dependency. FastAPI's dependency cache
    reuses the database session when the dependency is identical.
    """
    from app.authz.dependencies import require_permission

    normalized_entitlement_key = entitlement_key.strip()

    if not normalized_entitlement_key:
        raise ValueError("Entitlement key cannot be empty.")

    permission_dependency = require_permission(permission_key)

    def combined_dependency(
        tenant_context: TenantContext = Depends(permission_dependency),
        db: Session = Depends(get_db_session),
    ) -> TenantContext:
        value = get_entitlement_value(
            db,
            organization_id=tenant_context.organization_id,
            key=normalized_entitlement_key,
        )

        if value is not True:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This feature is not enabled for your subscription.",
            )

        return tenant_context

    return combined_dependency