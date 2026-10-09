"""Organization discovery endpoints for DealFlow."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.session import get_db_session


router = APIRouter(
    prefix="/api/v1/organizations",
    tags=["organizations"],
)


class OrganizationResponse(BaseModel):
    """An active organization accessible to the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


@router.get("", response_model=list[OrganizationResponse])
def list_my_organizations(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> list[OrganizationResponse]:
    """List organizations connected to the current user by active membership."""

    statement = (
        select(Organization)
        .join(
            Membership,
            Membership.organization_id == Organization.id,
        )
        .where(
            Membership.user_id == current_user.user_id,
            Membership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .order_by(Organization.name.asc(), Organization.id.asc())
    )

    organizations = db.scalars(statement).all()

    return [
        OrganizationResponse.model_validate(organization)
        for organization in organizations
    ]