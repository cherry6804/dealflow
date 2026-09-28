"""Tenant context dependencies for DealFlow."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def get_tenant_context(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    organization_id: UUID | None = Header(
        default=None,
        alias="X-Organization-ID",
    ),
    db: Session = Depends(get_db_session),
) -> TenantContext:
    """Resolve and verify the tenant context for the current request."""
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context is required.",
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