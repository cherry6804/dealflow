"""Authentication request and response schemas for DealFlow."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Credentials supplied when a user signs in."""

    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class AuthenticatedUserResponse(BaseModel):
    """Safe representation of the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str


class LoginResponse(BaseModel):
    """Response returned after successful authentication."""

    user: AuthenticatedUserResponse