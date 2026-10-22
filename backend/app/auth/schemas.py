
"""Authentication request and response schemas for DealFlow."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    """Credentials supplied when a user signs in."""

    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("Enter a valid email address.")
        return normalized


class SignupRequest(BaseModel):
    """Credentials and initial workspace details for new accounts."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=2, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if (
            not normalized
            or "@" not in normalized
            or normalized.startswith("@")
            or normalized.endswith("@")
            or "." not in normalized.rsplit("@", 1)[-1]
        ):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("display_name", "organization_name")
    @classmethod
    def normalize_required_names(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("This field cannot be empty.")
        return normalized


class AuthenticatedUserResponse(BaseModel):
    """Safe representation of the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str


class LoginResponse(BaseModel):
    """Response returned after successful authentication."""

    user: AuthenticatedUserResponse


class SignupOrganizationResponse(BaseModel):
    """Safe representation of the newly created workspace."""

    id: UUID
    name: str


class SignupResponse(BaseModel):
    """Response returned after successful signup."""

    user: AuthenticatedUserResponse
    organization: SignupOrganizationResponse
