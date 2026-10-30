"""Request and response schemas for team and role management."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)


RoleName = Annotated[str, StringConstraints(min_length=2, max_length=80)]
RoleDescription = Annotated[str, StringConstraints(max_length=500)]


class TeamRoleResponse(BaseModel):
    """Organization-scoped role metadata."""

    id: UUID
    name: str
    organization_id: UUID | None = None
    description: str | None = None
    is_system: bool = False
    is_active: bool = True
    permission_keys: list[str] = Field(default_factory=list)


class TeamRoleCreateRequest(BaseModel):
    """Create a custom role within the selected organization."""

    name: RoleName
    description: RoleDescription | None = None
    permission_keys: list[str] = Field(default_factory=list, max_length=200)


class TeamRoleUpdateRequest(BaseModel):
    """Update an organization-scoped custom role."""

    name: RoleName | None = None
    description: RoleDescription | None = None
    permission_keys: list[str] | None = Field(default=None, max_length=200)


class PermissionCatalogueItem(BaseModel):
    """A permission available to the role editor."""

    key: str
    description: str
    group: str
    assignable: bool = True


class TeamMemberResponse(BaseModel):
    """A member of the selected organization."""

    user_id: UUID
    display_name: str
    email: EmailStr
    membership_id: UUID
    roles: list[TeamRoleResponse]
    joined_at: datetime


class TeamMemberRoleUpdateRequest(BaseModel):
    """Replace a member's assignable role."""

    role_id: UUID


class TeamMemberRemovalRequest(BaseModel):
    """Optional reason recorded with the removal."""

    reason: str = Field(default="", max_length=500)


class TeamMemberRemovalResponse(BaseModel):
    """Result of removing a team member after SIBVO confirmed the seat outcome.

    `seat_outcome` is one of released, already_released, not_held or not_linked.
    A removal is never reported unless SIBVO confirmed it (or the member is not linked).
    """

    membership_id: UUID
    is_active: bool
    seat_outcome: str
    already_removed: bool = False
    message: str


class TeamInvitationCreateRequest(BaseModel):
    """Create an invitation for a new organization member."""

    email: EmailStr
    role_id: UUID


class TeamInvitationResponse(BaseModel):
    """Invitation metadata. Secret token material is never serialized."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    email: EmailStr
    role_id: UUID
    status: str
    invited_by_user_id: UUID
    accepted_by_user_id: UUID | None = None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


class TeamInvitationAcceptRequest(BaseModel):
    """Accept an invitation using its raw, single-use token."""

    token: str = Field(min_length=32, max_length=512)


class TeamInvitationAcceptResponse(BaseModel):
    """Result of accepting an invitation."""

    organization_id: UUID
    membership_id: UUID
    message: str