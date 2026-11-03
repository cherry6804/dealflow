"""Tenant context dependencies for DealFlow."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.audit.principal import bound_principal, issue_principal
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.session import get_db_session


@dataclass(frozen=True)
class TenantContext:
    """Represent the verified tenant context for the current request."""

    organization: Organization
    membership: Membership

    @property
    def organization_id(self) -> UUID:
        """Return the verified organization identifier."""
        return self.organization.id


def _resolve_tenant(
    current_user: CurrentUserContext,
    organization_id: UUID | None,
    db: Session,
) -> TenantContext:
    """Verify that the authenticated user holds an active membership in the requested organization."""
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context is required.",
        )

    if (
        current_user.session_organization_id is not None
        and organization_id != current_user.session_organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied.",
        )

    statement = (
        select(Membership)
        .join(Organization, Membership.organization_id == Organization.id)
        .where(
            Membership.user_id == current_user.user_id,
            Membership.organization_id == organization_id,
            Membership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
    )

    membership = db.scalar(statement)

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access denied.",
        )

    return TenantContext(
        organization=membership.organization,
        membership=membership,
    )


async def get_tenant_context(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    organization_id: UUID | None = Header(
        default=None,
        alias="X-Organization-ID",
    ),
    db: Session = Depends(get_db_session),
) -> AsyncIterator[TenantContext]:
    """Resolve and verify the tenant context, and bind the authenticated principal for the request.

    This is an async generator on purpose. A context variable set here is visible to the endpoint and to the
    services it calls, and it is reset when the request ends. The database check runs in a worker thread so
    the event loop is not blocked.
    """
    tenant = await run_in_threadpool(_resolve_tenant, current_user, organization_id, db)
    principal = issue_principal(
        user_id=current_user.user_id,
        organization_id=tenant.organization_id,
    )
    with bound_principal(principal):
        yield tenant
