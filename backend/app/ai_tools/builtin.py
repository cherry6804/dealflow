"""Approved read-only tools for this release (DFR1-018).

Each handler reuses an existing service, and each returns the minimum an agent needs. Contact details that are personal
data (email, phone) are not returned, because a tool result can be sent to an external model provider, and provider data-use
terms are not approved (E01 matrix). A missing contact and another organization's contact return the same answer, so the
tool does not reveal whether a record exists in another tenant.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai_tools.definitions import ParameterType, ToolDefinition, ToolParameter
from app.contacts.service import get_contact

CONTACT_GET = "contacts.get"
ASSISTANT_CAPABILITY = "ai.assistant"


def _contact_get(db: Session, organization_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    contact = get_contact(db, organization_id=organization_id, contact_id=arguments["contact_id"])
    if contact is None:
        return {"found": False}
    name = " ".join(part for part in (contact.first_name, contact.last_name) if part)
    return {
        "found": True,
        "contact": {
            "id": str(contact.id),
            "display_name": name,
            "is_active": bool(contact.is_active),
        },
    }


BUILTIN_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        key=CONTACT_GET,
        description="Look up one contact in the current organization by its identifier. Returns the display name and status.",
        capability_key=ASSISTANT_CAPABILITY,
        required_permission="contacts.read",
        parameters=(ToolParameter(name="contact_id", type=ParameterType.UUID),),
        handler=_contact_get,
    ),
)
