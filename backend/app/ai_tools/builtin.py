"""Approved read-only tools for this release (DFR1-018).

Each handler reuses an existing service, and each returns the minimum an agent needs. Contact details that are personal
data (email, phone) are not returned, because a tool result can be sent to an external model provider, and provider data-use
terms are not approved (E01 matrix). A missing contact and another organization's contact return the same answer, so the
tool does not reveal whether a record exists in another tenant.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_tools.definitions import (
    OutputField,
    OutputType,
    ParameterType,
    ToolDefinition,
    ToolParameter,
)
from app.contacts.service import get_contact
from app.db.models.deal import Deal
from app.leads.service import get_lead
from app.properties.service import get_property
from app.requirements.service import get_customer_requirement

CONTACT_GET = "contacts.get"
LEADS_GET = "leads.get"
REQUIREMENTS_GET = "requirements.get"
PROPERTIES_GET = "properties.get"
DEALS_GET = "deals.get"
ASSISTANT_CAPABILITY = "ai.assistant"


def _text(value: object) -> str | None:
    """A decimal, date or identifier as text, or None when the record does not have it."""
    return None if value is None else str(value)


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


def _leads_get(db: Session, organization_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    # next_action is free text written by a user, so it is not returned.
    lead = get_lead(db, organization_id=organization_id, lead_id=arguments["lead_id"])
    if lead is None:
        return {"found": False}
    return {
        "found": True,
        "lead": {
            "id": str(lead.id),
            "contact_id": str(lead.contact_id),
            "status": lead.status,
            "interest": lead.interest,
            "outcome": lead.outcome,
            "next_action_at": _text(lead.next_action_at),
            "is_active": bool(lead.is_active),
        },
    }


def _requirements_get(db: Session, organization_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    # The customer's name, email and phone are personal data and are not returned.
    requirement = get_customer_requirement(db, organization_id=organization_id, requirement_id=arguments["requirement_id"])
    if requirement is None:
        return {"found": False}
    return {
        "found": True,
        "requirement": {
            "id": str(requirement.id),
            "status": requirement.status,
            "is_active": bool(requirement.is_active),
            "budget_min": _text(requirement.budget_min),
            "budget_max": _text(requirement.budget_max),
            "budget_currency": requirement.budget_currency,
        },
    }


def _properties_get(db: Session, organization_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    # Street address lines and the source and owner contacts are not returned. Inventory facts are.
    property_record = get_property(db, organization_id=organization_id, property_id=arguments["property_id"])
    if property_record is None:
        return {"found": False}
    return {
        "found": True,
        "property": {
            "id": str(property_record.id),
            "status": property_record.status,
            "transaction_type": property_record.transaction_type,
            "property_type": property_record.property_type,
            "city": property_record.city,
            "locality": property_record.locality,
            "bhk": property_record.bhk,
            "price": _text(property_record.price),
            "currency": property_record.currency,
        },
    }


def _deals_get(db: Session, organization_id: UUID, arguments: dict[str, Any]) -> dict[str, Any]:
    # A plain read: unlike the service's get_deal, this takes no row lock, so a read cannot block a stage transition.
    # Free-text notes and the owner's name are not returned.
    deal = db.scalar(select(Deal).where(Deal.id == arguments["deal_id"], Deal.organization_id == organization_id))
    if deal is None:
        return {"found": False}
    return {
        "found": True,
        "deal": {
            "id": str(deal.id),
            "stage": deal.stage,
            "expected_value": _text(deal.expected_value),
            "currency": deal.currency,
            "property_id": str(deal.property_id),
            "lead_id": _text(deal.lead_id),
            "customer_profile_id": str(deal.customer_profile_id),
        },
    }


def _found(entity: str, fields: tuple[OutputField, ...]) -> tuple[OutputField, ...]:
    """A lookup result: a found flag, and the record's object when it was found."""
    return (
        OutputField("found", OutputType.BOOLEAN),
        OutputField(entity, OutputType.OBJECT, required=False, fields=fields),
    )


CONTACT_OUTPUT = _found(
    "contact",
    (
        OutputField("id", OutputType.STRING),
        OutputField("display_name", OutputType.STRING),
        OutputField("is_active", OutputType.BOOLEAN),
    ),
)
LEAD_OUTPUT = _found(
    "lead",
    (
        OutputField("id", OutputType.STRING),
        OutputField("contact_id", OutputType.STRING),
        OutputField("status", OutputType.STRING),
        OutputField("interest", OutputType.STRING, nullable=True),
        OutputField("outcome", OutputType.STRING, nullable=True),
        OutputField("next_action_at", OutputType.STRING, nullable=True),
        OutputField("is_active", OutputType.BOOLEAN),
    ),
)
REQUIREMENT_OUTPUT = _found(
    "requirement",
    (
        OutputField("id", OutputType.STRING),
        OutputField("status", OutputType.STRING),
        OutputField("is_active", OutputType.BOOLEAN),
        OutputField("budget_min", OutputType.STRING, nullable=True),
        OutputField("budget_max", OutputType.STRING, nullable=True),
        OutputField("budget_currency", OutputType.STRING, nullable=True),
    ),
)
PROPERTY_OUTPUT = _found(
    "property",
    (
        OutputField("id", OutputType.STRING),
        OutputField("status", OutputType.STRING, nullable=True),
        OutputField("transaction_type", OutputType.STRING, nullable=True),
        OutputField("property_type", OutputType.STRING, nullable=True),
        OutputField("city", OutputType.STRING, nullable=True),
        OutputField("locality", OutputType.STRING, nullable=True),
        OutputField("bhk", OutputType.INTEGER, nullable=True),
        OutputField("price", OutputType.STRING, nullable=True),
        OutputField("currency", OutputType.STRING, nullable=True),
    ),
)
DEAL_OUTPUT = _found(
    "deal",
    (
        OutputField("id", OutputType.STRING),
        OutputField("stage", OutputType.STRING),
        OutputField("expected_value", OutputType.STRING, nullable=True),
        OutputField("currency", OutputType.STRING),
        OutputField("property_id", OutputType.STRING),
        OutputField("lead_id", OutputType.STRING, nullable=True),
        OutputField("customer_profile_id", OutputType.STRING),
    ),
)


BUILTIN_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        key=CONTACT_GET,
        target_type="contact",
        target_parameter="contact_id",
        description="Look up one contact in the current organization by its identifier. Returns the display name and status.",
        capability_key=ASSISTANT_CAPABILITY,
        required_permission="contacts.read",
        parameters=(ToolParameter(name="contact_id", type=ParameterType.UUID),),
        output_schema=CONTACT_OUTPUT,
        handler=_contact_get,
    ),
    ToolDefinition(
        key=LEADS_GET,
        target_type="lead",
        target_parameter="lead_id",
        description="Look up one lead in the current organization. Returns its status, interest, outcome and next action time.",
        capability_key=ASSISTANT_CAPABILITY,
        required_permission="leads.read",
        parameters=(ToolParameter(name="lead_id", type=ParameterType.UUID),),
        output_schema=LEAD_OUTPUT,
        handler=_leads_get,
    ),
    ToolDefinition(
        key=REQUIREMENTS_GET,
        target_type="requirement",
        target_parameter="requirement_id",
        description="Look up one customer requirement in the current organization. Returns its status and budget, not the customer's details.",
        capability_key=ASSISTANT_CAPABILITY,
        required_permission="requirements.read",
        parameters=(ToolParameter(name="requirement_id", type=ParameterType.UUID),),
        output_schema=REQUIREMENT_OUTPUT,
        handler=_requirements_get,
    ),
    ToolDefinition(
        key=PROPERTIES_GET,
        target_type="property",
        target_parameter="property_id",
        description="Look up one property in the current organization inventory. Returns its status, type, location and price, not its street address.",
        capability_key=ASSISTANT_CAPABILITY,
        required_permission="properties.read",
        parameters=(ToolParameter(name="property_id", type=ParameterType.UUID),),
        output_schema=PROPERTY_OUTPUT,
        handler=_properties_get,
    ),
    ToolDefinition(
        key=DEALS_GET,
        target_type="deal",
        target_parameter="deal_id",
        description="Look up one deal in the current organization. Returns its stage, value and linked references, not its notes.",
        capability_key=ASSISTANT_CAPABILITY,
        required_permission="deals.read",
        parameters=(ToolParameter(name="deal_id", type=ParameterType.UUID),),
        output_schema=DEAL_OUTPUT,
        handler=_deals_get,
    ),
)
