
"""Pydantic schemas for automation-rule management."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AutomationRuleCreateRequest(BaseModel):
    """Request to create a draft automation rule."""

    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=20_000)
    trigger_type: str = Field(min_length=1, max_length=100)
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name", "trigger_type")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AutomationRuleUpdateRequest(BaseModel):
    """Request to update a rule's configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=20_000)
    trigger_type: str | None = Field(default=None, min_length=1, max_length=100)
    trigger_config: dict[str, Any] | None = None
    conditions: list[dict[str, Any]] | None = None
    actions: list[dict[str, Any]] | None = None

    @field_validator("name", "trigger_type")
    @classmethod
    def normalize_required_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_optional_description(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AutomationRuleResponse(BaseModel):
    """Public representation of an automation rule."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    status: str
    created_by_user_id: UUID | None
    updated_by_user_id: UUID | None
    created_at: Any
    updated_at: Any


class AutomationRuleListResponse(BaseModel):
    """Paginated list of automation rules."""

    items: list[AutomationRuleResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
