"""Background execution of privacy export and deletion requests (DFR1-050).

A request record (``app.governance.privacy``) does no work. This module does the work, from an
outbox event enqueued when a request is created. The handler is idempotent: a request is
processed only while it is in its first state, so a retry or a duplicate event changes nothing.

Exports
- Generates one ZIP artifact per request: ``export.json`` with a coverage section, plus the stored
  document files. Every requested category is either exported or listed under ``not_exported``
  with a reason. An artifact never implies completeness it does not have.
- Documents are all-or-nothing: a missing object, a checksum mismatch, or a total over the
  configured size limit excludes the whole category rather than exporting part of it.
- The artifact is stored under one key per request, so a retry replaces it and cannot orphan
  an object. Download is organization-scoped, permission-checked, audited and refused after expiry.

Deletions
- Re-evaluates eligibility at execution time, so a legal hold placed after the request blocks it.
- Documents: stored object, then metadata row. A missing object counts as already removed.
- Team invitations: the email address is replaced by a non-deliverable placeholder, and a pending
  invitation is revoked, so it can no longer be accepted for that address.
- Contacts: identity fields are anonymized. Linked records are not changed, so the category is
  ``anonymized_partial``, never a full deletion.
- Every other eligible category is ``not_executed``. The request then ends ``partially_completed``.

Retention (``enforce_retention``) applies configured periods to documents and team invitations only.
It uses the same executors, checks legal holds, and audits each run. See
``app.governance.privacy_maintenance`` for the scheduled entry point.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.activity import Activity
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_history import CustomerRequirementHistory
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_possession_parking_preference import (
    CustomerRequirementPossessionParkingPreference,
)
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.deal import Deal
from app.db.models.deal_commission import DealCommission
from app.db.models.deal_negotiation import DealNegotiation, DealNegotiationHistory
from app.db.models.deal_stage_history import DealStageHistory
from app.db.models.document import Document
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.outbox_event import OutboxEvent
from app.db.models.payment_milestone import PaymentMilestone
from app.db.models.privacy_records import PrivacyDataRequest, RetentionPolicy
from app.db.models.property import Property
from app.db.models.referral import Referral
from app.db.models.team_invitation import TeamInvitation
from app.governance.data_classification import CATEGORY_BY_KEY
from app.governance.privacy import (
    REASON_EXECUTOR_NOT_BUILT,
    REASON_NO_EXPORT_PRODUCER,
    REASON_NO_PRODUCER,
    REASON_NOT_ORGANIZATION_OWNED,
    STATUS_AWAITING_ARTIFACT,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_ELIGIBILITY_RECORDED,
    STATUS_EXPIRED,
    STATUS_PARTIALLY_COMPLETED,
    STATUS_READY,
    STATUS_READY_PARTIAL,
    InvalidRequestStateError,
    current_retention,
    evaluate_deletion,
    expire_export_if_due,
    record_completed_privacy_event,
    record_requested_privacy_event,
)
from app.outbox.service import enqueue_event, register_handler
from app.storage import ObjectNotFoundError, ObjectStorage, get_object_storage

PRIVACY_PROCESS_EVENT_TYPE = "privacy.request.process"
PRIVACY_AGGREGATE_TYPE = "privacy_request"
EXPORT_KEY_PREFIX = "privacy-exports"
EXPORT_JSON_MEMBER = "export.json"
DOCUMENT_MEMBER_PREFIX = "files"
REDACTED_NAME = "Redacted"
REDACTED_EMAIL_DOMAIN = "redacted.invalid"

DOCUMENTS_CATEGORY = "documents.files"
CONTACTS_CATEGORY = "crm.contacts"
INVITATIONS_CATEGORY = "team.invitations"
EMAIL_CATEGORY = "messaging.email_outbox"

REASON_STORED_OBJECT_MISSING = "stored_object_missing"
REASON_STORED_OBJECT_CHECKSUM = "stored_object_checksum_mismatch"
REASON_EXPORT_SIZE_LIMIT = "export_size_limit_exceeded"
REASON_ENCRYPTED_PAYLOAD = "encrypted_payload_not_exportable"
REASON_RETENTION_NOT_ENFORCED = "retention_enforcement_not_built"

OUTCOME_DELETED = "deleted"
OUTCOME_ANONYMIZED = "anonymized"
OUTCOME_ANONYMIZED_PARTIAL = "anonymized_partial"
OUTCOME_NOT_EXECUTED = "not_executed"
OUTCOME_SKIPPED = "skipped"

# Only these outcomes complete a category. Anything partial keeps the request partial.
OUTCOMES_FULL = frozenset({OUTCOME_DELETED, OUTCOME_ANONYMIZED})
OUTCOMES_PERFORMED = frozenset(
    {OUTCOME_DELETED, OUTCOME_ANONYMIZED, OUTCOME_ANONYMIZED_PARTIAL}
)

# Exclusions decided by data shape, not by policy: no exporter can produce these honestly.
EXPORT_EXCLUSIONS: dict[str, str] = {
    EMAIL_CATEGORY: REASON_NOT_ORGANIZATION_OWNED,
}

# Categories the retention job enforces. Contacts are excluded on purpose: whether an old contact
# may be anonymized while deals still reference it is a product and legal decision.
RETENTION_ENFORCED: tuple[str, ...] = (DOCUMENTS_CATEGORY, INVITATIONS_CATEGORY)

_SAFE_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")


class PrivacyExecutionError(Exception):
    """Raised when a privacy request cannot be processed or served."""


class ExportUnavailableError(PrivacyExecutionError):
    """The export is not ready, or it has expired."""


class PrivacyRequestNotFoundError(PrivacyExecutionError):
    """No request with this ID exists in the organization."""


class CategoryNotExportedError(Exception):
    """Raised inside an exporter when its category cannot be exported completely."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def export_storage_key(organization_id: UUID, request_id: UUID) -> str:
    # One key per request. A retry replaces the object, so no attempt can leave an orphan behind.
    return f"{EXPORT_KEY_PREFIX}/{organization_id}/{request_id}.zip"


def _export_contacts(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Contact)
        .where(Contact.organization_id == organization_id)
        .order_by(Contact.created_at, Contact.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "first_name": row.first_name,
            "last_name": row.last_name,
            "email": row.email,
            "phone": row.phone,
            "is_active": row.is_active,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_leads(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Lead)
        .where(Lead.organization_id == organization_id)
        .order_by(Lead.created_at, Lead.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "contact_id": str(row.contact_id),
            "status": row.status,
            "interest": row.interest,
            "outcome": row.outcome,
            "next_action": row.next_action,
            "is_active": row.is_active,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_follow_ups(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(FollowUp)
        .where(FollowUp.organization_id == organization_id)
        .order_by(FollowUp.created_at, FollowUp.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "lead_id": str(row.lead_id),
            "follow_up_type": row.follow_up_type,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "due_at": _iso(row.due_at),
            "completed_at": _iso(row.completed_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_requirement_locations(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CustomerRequirementLocation)
        .where(CustomerRequirementLocation.organization_id == organization_id)
        .order_by(CustomerRequirementLocation.created_at, CustomerRequirementLocation.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "city": row.city,
            "locality": row.locality,
            "is_active": row.is_active,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_requirement_property_preferences(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CustomerRequirementPropertyPreference)
        .where(CustomerRequirementPropertyPreference.organization_id == organization_id)
        .order_by(CustomerRequirementPropertyPreference.created_at, CustomerRequirementPropertyPreference.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "property_type": row.property_type,
            "bhk_min": row.bhk_min,
            "bhk_max": row.bhk_max,
            "is_active": row.is_active,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_requirement_parking_preferences(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CustomerRequirementPossessionParkingPreference)
        .where(CustomerRequirementPossessionParkingPreference.organization_id == organization_id)
        .order_by(CustomerRequirementPossessionParkingPreference.created_at)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "possession_preference": row.possession_preference,
            "parking_preference": row.parking_preference,
            "parking_spaces_min": row.parking_spaces_min,
            "is_active": row.is_active,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_requirement_history(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CustomerRequirementHistory)
        .where(CustomerRequirementHistory.organization_id == organization_id)
        .order_by(CustomerRequirementHistory.occurred_at, CustomerRequirementHistory.id)
    ).all()
    # The actor is an internal identifier and is not exported.
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "version": row.version,
            "change_type": row.change_type,
            "occurred_at": _iso(row.occurred_at),
            "snapshot": row.snapshot,
        }
        for row in rows
    ]


def _export_deal_negotiations(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DealNegotiation)
        .where(DealNegotiation.organization_id == organization_id)
        .order_by(DealNegotiation.created_at, DealNegotiation.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "deal_id": str(row.deal_id),
            "state": row.state,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }
        for row in rows
    ]


def _export_deal_negotiation_history(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DealNegotiationHistory)
        .where(DealNegotiationHistory.organization_id == organization_id)
        .order_by(DealNegotiationHistory.created_at, DealNegotiationHistory.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "negotiation_id": str(row.negotiation_id),
            "from_state": row.from_state,
            "to_state": row.to_state,
            "note": row.note,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_deal_stage_history(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DealStageHistory)
        .where(DealStageHistory.organization_id == organization_id)
        .order_by(DealStageHistory.created_at, DealStageHistory.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "deal_id": str(row.deal_id),
            "from_stage": row.from_stage,
            "to_stage": row.to_stage,
            "reason": row.reason,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_activities(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Activity records. ``details`` (unreviewed JSON) and the actor identifier are not exported yet."""
    rows = db.scalars(
        select(Activity)
        .where(Activity.organization_id == organization_id)
        .order_by(Activity.created_at, Activity.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "lead_id": str(row.lead_id) if row.lead_id is not None else None,
            "activity_type": row.activity_type,
            "title": row.title,
            "description": row.description,
            "occurred_at": _iso(row.occurred_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_invitations(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    # The token hash is a credential and is never exported.
    rows = db.scalars(
        select(TeamInvitation)
        .where(TeamInvitation.organization_id == organization_id)
        .order_by(TeamInvitation.created_at, TeamInvitation.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "email": row.email,
            "status": row.status,
            "created_at": _iso(row.created_at),
            "expires_at": _iso(row.expires_at),
            "accepted_at": _iso(row.accepted_at),
            "revoked_at": _iso(row.revoked_at),
        }
        for row in rows
    ]


def _safe_extension(value: str | None) -> str:
    candidate = (value or "").lower()
    return candidate if _SAFE_EXTENSION.fullmatch(candidate) else ""


def _export_documents(
    db: Session,
    organization_id: UUID,
    storage: ObjectStorage,
    *,
    max_bytes: int,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Export every document with its stored file, or none of them."""
    documents = db.scalars(
        select(Document)
        .where(Document.organization_id == organization_id)
        .order_by(Document.created_at, Document.id)
    ).all()
    declared = sum(document.file_size_bytes or 0 for document in documents)
    if declared > max_bytes:
        raise CategoryNotExportedError(REASON_EXPORT_SIZE_LIMIT)

    rows: list[dict[str, Any]] = []
    members: dict[str, bytes] = {}
    total = 0
    for document in documents:
        if not document.storage_key:
            raise CategoryNotExportedError(REASON_STORED_OBJECT_MISSING)
        try:
            with storage.open_read(document.storage_key) as handle:
                content = handle.read(max_bytes - total + 1)
        except ObjectNotFoundError as error:
            raise CategoryNotExportedError(REASON_STORED_OBJECT_MISSING) from error
        total += len(content)
        if total > max_bytes:
            raise CategoryNotExportedError(REASON_EXPORT_SIZE_LIMIT)
        if hashlib.sha256(content).hexdigest() != document.checksum_sha256:
            raise CategoryNotExportedError(REASON_STORED_OBJECT_CHECKSUM)

        member = f"{DOCUMENT_MEMBER_PREFIX}/{document.id}{_safe_extension(document.file_extension)}"
        members[member] = content
        rows.append(
            {
                "id": str(document.id),
                "original_filename": document.original_filename,
                "display_name": document.display_name,
                "category": document.category,
                "document_type": document.document_type,
                "content_type": document.content_type,
                "file_size_bytes": document.file_size_bytes,
                "checksum_sha256": document.checksum_sha256,
                "created_at": _iso(document.created_at),
                "archive_path": member,
            }
        )
    return rows, members


def _export_customer_profiles(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CustomerProfile)
        .where(CustomerProfile.organization_id == organization_id)
        .order_by(CustomerProfile.created_at, CustomerProfile.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "contact_id": str(row.contact_id),
            "is_active": row.is_active,
            "customer_notes": row.customer_notes,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_requirements(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(CustomerRequirement)
        .where(CustomerRequirement.organization_id == organization_id)
        .order_by(CustomerRequirement.created_at, CustomerRequirement.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "lead_id": str(row.lead_id),
            "customer_profile_id": str(row.customer_profile_id),
            "status": row.status,
            "is_active": row.is_active,
            "budget_min": row.budget_min,
            "budget_max": row.budget_max,
            "budget_currency": row.budget_currency,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_deals(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Deals with their payment milestones and commissions. Financial records are exported, not changed."""
    deals = db.scalars(
        select(Deal).where(Deal.organization_id == organization_id).order_by(Deal.created_at, Deal.id)
    ).all()
    milestones = db.scalars(
        select(PaymentMilestone).where(PaymentMilestone.organization_id == organization_id)
    ).all()
    commissions = db.scalars(
        select(DealCommission).where(DealCommission.organization_id == organization_id)
    ).all()
    milestones_by_deal: dict[UUID, list[dict[str, Any]]] = {}
    for row in milestones:
        milestones_by_deal.setdefault(row.deal_id, []).append(
            {
                "id": str(row.id),
                "name": row.name,
                "amount": row.amount,
                "currency": row.currency,
                "due_at": _iso(row.due_at),
                "status": row.status,
                "paid_at": _iso(row.paid_at),
                "notes": row.notes,
            }
        )
    commissions_by_deal: dict[UUID, list[dict[str, Any]]] = {}
    for row in commissions:
        commissions_by_deal.setdefault(row.deal_id, []).append(
            {
                "id": str(row.id),
                "commission_type": row.commission_type,
                "fixed_amount": row.fixed_amount,
                "rate_percent": str(row.rate_percent) if row.rate_percent is not None else None,
                "currency": row.currency,
                "status": row.status,
                "terms": row.terms,
                "agreed_at": _iso(row.agreed_at),
                "paid_at": _iso(row.paid_at),
            }
        )
    return [
        {
            "id": str(deal.id),
            "lead_id": str(deal.lead_id),
            "customer_profile_id": str(deal.customer_profile_id),
            "property_id": str(deal.property_id),
            "stage": deal.stage,
            "expected_value": deal.expected_value,
            "currency": deal.currency,
            "notes": deal.notes,
            "created_at": _iso(deal.created_at),
            "payment_milestones": milestones_by_deal.get(deal.id, []),
            "commissions": commissions_by_deal.get(deal.id, []),
        }
        for deal in deals
    ]


def _export_ai_usage(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Usage metering only. Stored by the ledger; it holds no prompt or response text."""
    rows = db.scalars(
        select(AiUsageEvent)
        .where(AiUsageEvent.organization_id == organization_id)
        .order_by(AiUsageEvent.occurred_at, AiUsageEvent.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "unit": row.unit,
            "reserved_quantity": row.reserved_quantity,
            "quantity": row.quantity,
            "status": row.status,
            "provider": row.provider,
            "model": row.model,
            "task_type": row.task_type,
            "capability_key": row.capability_key,
            "occurred_at": _iso(row.occurred_at),
        }
        for row in rows
    ]


EXPORTERS: dict[str, Callable[[Session, UUID], list[dict[str, Any]]]] = {
    CONTACTS_CATEGORY: _export_contacts,
    "crm.leads": _export_leads,
    "crm.follow_ups": _export_follow_ups,
    "crm.customer_profiles": _export_customer_profiles,
    "crm.requirements": _export_requirements,
    "crm.deals": _export_deals,
    "ai.usage": _export_ai_usage,
    INVITATIONS_CATEGORY: _export_invitations,
}

# CRM sub-records are exported under their parent category. Each list is part of that category.
SUB_RECORD_EXPORTERS: dict[str, dict[str, Callable[[Session, UUID], list[dict[str, Any]]]]] = {
    "crm.requirements": {
        "requirement_locations": _export_requirement_locations,
        "requirement_property_preferences": _export_requirement_property_preferences,
        "requirement_parking_preferences": _export_requirement_parking_preferences,
        "requirement_history": _export_requirement_history,
    },
    "crm.deals": {
        "negotiations": _export_deal_negotiations,
        "negotiation_history": _export_deal_negotiation_history,
        "stage_history": _export_deal_stage_history,
    },
    "crm.follow_ups": {
        "activities": _export_activities,
    },
}

# Organization-owned tables that no export covers. Every artifact lists them, so none is left out silently.
NOT_COVERED_TABLES: tuple[dict[str, str], ...] = (
    {"table": "billing_reconciliation_records", "classification": "billing.records", "reason": "Excluded by decision D3 until sensitive-field filtering and authorization are approved."},
    {"table": "audit_events", "classification": "audit.events", "reason": "Excluded by decision D3 until sensitive-field filtering and authorization are approved."},
    {"table": "properties", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "site_visits", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "referrals", "classification": "unclassified", "reason": "Pending classification (decision D9). Contains personal contact details."},
    {"table": "notifications", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "notification_preferences", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "import_batches", "classification": "unclassified, document-like (decision D13)", "reason": "Ownership, dependencies and retention to be confirmed before export or deletion."},
    {"table": "organization_memberships", "classification": "SIBVO-owned (decision D6)", "reason": "SIBVO is the authority for membership. Requests are answered by SIBVO."},
    {"table": "subscriptions", "classification": "SIBVO-owned (decision D6)", "reason": "SIBVO is the authority for subscriptions and billing. Requests are answered by SIBVO."},
    {"table": "roles", "classification": "configuration", "reason": "Pending classification (decision D9)."},
    {"table": "organization_capability_settings", "classification": "configuration", "reason": "Pending classification (decision D9)."},
    {"table": "organization_usage_budgets", "classification": "configuration and billing", "reason": "Pending classification (decision D9)."},
    {"table": "auth_sessions", "classification": "security", "reason": "Never exported. Contains session credentials."},
    {"table": "automation_rules", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "automation_executions", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "requirement_match_runs", "classification": "unclassified, derived", "reason": "Pending classification (decision D9)."},
    {"table": "requirement_match_run_results", "classification": "unclassified, derived", "reason": "Pending classification (decision D9)."},
    {"table": "requirement_property_shortlists", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "requirement_shortlist_events", "classification": "unclassified", "reason": "Pending classification (decision D9)."},
    {"table": "team_member_removals", "classification": "unclassified, personal removal reasons", "reason": "Pending classification (decision D9)."},
    {"table": "email_outbox_messages", "classification": "platform, no organization column", "reason": "Outside organization export and deletion (decision D5)."},
    {"table": "privacy_data_requests", "classification": "governance record", "reason": "Request records are not customer data. Retained as governance evidence."},
    {"table": "privacy_legal_holds", "classification": "governance record", "reason": "Hold records are not customer data. Retained as governance evidence."},
    {"table": "privacy_retention_policies", "classification": "governance record", "reason": "Policy records are not customer data. Retained as governance evidence."},
    {"table": "outbox_events", "classification": "system record", "reason": "Not customer data."},
)


def enqueue_processing(db: Session, request: PrivacyDataRequest) -> None:
    """Queue background processing. The caller commits with the request."""
    enqueue_event(
        db,
        organization_id=request.organization_id,
        event_type=PRIVACY_PROCESS_EVENT_TYPE,
        aggregate_type=PRIVACY_AGGREGATE_TYPE,
        aggregate_id=str(request.id),
        idempotency_key=f"privacy-request:{request.id}:process",
        payload={"request_id": str(request.id)},
    )


def _default_export_reason(category_key: str) -> str:
    if category_key in EXPORT_EXCLUSIONS:
        return EXPORT_EXCLUSIONS[category_key]
    category = CATEGORY_BY_KEY[category_key]
    if not category.organization_owned:
        return REASON_NOT_ORGANIZATION_OWNED
    return REASON_NO_EXPORT_PRODUCER if category.producer_exists else REASON_NO_PRODUCER


def _build_archive(document: dict[str, Any], members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            EXPORT_JSON_MEMBER,
            json.dumps(document, sort_keys=True, default=str).encode("utf-8"),
        )
        for name, content in sorted(members.items()):
            archive.writestr(name, content)
    return buffer.getvalue()


def generate_export(
    db: Session,
    request: PrivacyDataRequest,
    *,
    storage: ObjectStorage,
    now: datetime,
    max_bytes: int,
    ttl: timedelta,
) -> None:
    """Build and store the export artifact. No-op unless the request awaits generation."""
    if request.request_type != PrivacyDataRequest.TYPE_EXPORT:
        raise InvalidRequestStateError("Only export requests have artifacts.")
    if request.status != STATUS_AWAITING_ARTIFACT:
        return

    started = record_requested_privacy_event(
        db,
        organization_id=request.organization_id,
        actor_user_id=None,
        action="privacy.export.generation",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={"categories": json.loads(request.categories), "requested_by_user_id": str(request.requested_by_user_id)},
    )
    requested: list[str] = json.loads(request.categories)
    included: dict[str, list[dict[str, Any]]] = {}
    members: dict[str, bytes] = {}
    not_exported: list[dict[str, str]] = []
    for key in requested:
        try:
            if key == DOCUMENTS_CATEGORY:
                rows, document_members = _export_documents(
                    db, request.organization_id, storage, max_bytes=max_bytes
                )
                members.update(document_members)
            elif key in EXPORTERS and key not in EXPORT_EXCLUSIONS:
                rows = EXPORTERS[key](db, request.organization_id)
            else:
                raise CategoryNotExportedError(_default_export_reason(key))
        except CategoryNotExportedError as error:
            not_exported.append({"category_key": key, "reason": error.reason})
            continue
        included[key] = rows
        for name, sub_exporter in SUB_RECORD_EXPORTERS.get(key, {}).items():
            included[f"{key}/{name}"] = sub_exporter(db, request.organization_id)

    request.attempt_count += 1
    request.processed_at = now
    request.execution = json.dumps({"not_exported": not_exported}, sort_keys=True)
    if not included:
        request.status = STATUS_BLOCKED
        record_completed_privacy_event(
            db,
            requested=started,
            action="privacy.export.blocked",
            resource_type="privacy_request",
            resource_id=str(request.id),
            metadata={"not_exported": not_exported},
        )
        db.flush()
        return

    document = {
        "organization_id": str(request.organization_id),
        "request_id": str(request.id),
        "generated_at": now.isoformat(),
        "coverage": {
            "exported": sorted(included),
            "not_exported": not_exported,
            # Organization-owned data that no export covers. Listed in every artifact, never silently omitted.
            "not_covered": [dict(item) for item in NOT_COVERED_TABLES],
        },
        "categories": included,
    }
    key = export_storage_key(request.organization_id, request.id)
    archive = _build_archive(document, members)
    try:
        storage.delete(key)
    except ObjectNotFoundError:
        pass
    storage.put(key, io.BytesIO(archive))

    request.artifact_reference = key
    request.expires_at = now + ttl
    request.status = STATUS_READY if not not_exported else STATUS_READY_PARTIAL
    record_completed_privacy_event(
        db,
        requested=started,
        action="privacy.export.ready",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={
            "status": request.status,
            "exported": sorted(included),
            "not_exported": not_exported,
            "expires_at": request.expires_at.isoformat(),
        },
    )
    db.flush()


@dataclass(frozen=True)
class _Execution:
    outcome: str
    count: int = 0
    deferred: int = 0
    not_changed: tuple[str, ...] = ()


def _delete_documents(
    db: Session,
    organization_id: UUID,
    storage: ObjectStorage,
    *,
    cutoff: datetime | None = None,
) -> tuple[int, list[str]]:
    query = select(Document).where(Document.organization_id == organization_id)
    if cutoff is not None:
        query = query.where(Document.created_at < cutoff)
    documents = db.scalars(query).all()
    keys: list[str] = []
    for document in documents:
        if document.storage_key:
            keys.append(document.storage_key)
            try:
                storage.delete(document.storage_key)
            except ObjectNotFoundError:
                # Removed by an earlier attempt. The row removal below still completes.
                pass
        db.delete(document)
    db.flush()
    return len(documents), keys


def _verify_documents(
    db: Session,
    organization_id: UUID,
    storage: ObjectStorage,
    keys: list[str],
    *,
    cutoff: datetime | None,
) -> bool:
    query = select(func.count(Document.id)).where(Document.organization_id == organization_id)
    if cutoff is not None:
        query = query.where(Document.created_at < cutoff)
    if db.scalar(query):
        return False
    return not any(storage.exists(key) for key in keys)


def _verify_contacts(db: Session, organization_id: UUID) -> bool:
    """No contact that is free of dependencies may still hold its identity."""
    dependent = _dependent_contact_ids(db, organization_id)
    unredacted = db.scalars(
        select(Contact.id).where(
            Contact.organization_id == organization_id,
            Contact.first_name != REDACTED_NAME,
        )
    ).all()
    return all(contact_id in dependent for contact_id in unredacted)


def _verify_invitations(db: Session, organization_id: UUID, *, cutoff: datetime | None) -> bool:
    query = select(func.count(TeamInvitation.id)).where(
        TeamInvitation.organization_id == organization_id,
        TeamInvitation.email.not_like(f"redacted-%@{REDACTED_EMAIL_DOMAIN}"),
    )
    if cutoff is not None:
        query = query.where(TeamInvitation.created_at < cutoff)
    return db.scalar(query) == 0


def _dependent_contact_ids(db: Session, organization_id: UUID) -> set[UUID]:
    """Contacts that a live record still references. These are never anonymized by a deletion."""
    lead_contacts = set(
        db.scalars(select(Lead.contact_id).where(Lead.organization_id == organization_id)).all()
    )
    profile_contacts = set(
        db.scalars(
            select(CustomerProfile.contact_id).where(CustomerProfile.organization_id == organization_id)
        ).all()
    )
    property_owners = set(
        db.scalars(
            select(Property.owner_contact_id).where(
                Property.organization_id == organization_id, Property.owner_contact_id.is_not(None)
            )
        ).all()
    )
    property_sources = set(
        db.scalars(
            select(Property.source_contact_id).where(
                Property.organization_id == organization_id, Property.source_contact_id.is_not(None)
            )
        ).all()
    )
    referrers = set(
        db.scalars(
            select(Referral.referrer_contact_id).where(
                Referral.organization_id == organization_id, Referral.referrer_contact_id.is_not(None)
            )
        ).all()
    )
    return lead_contacts | profile_contacts | property_owners | property_sources | referrers


def _anonymize_contacts(db: Session, organization_id: UUID) -> tuple[int, int]:
    """Anonymize contacts that no lead or customer profile depends on. Return (anonymized, deferred).

    A contact still referenced by a lead or a customer profile is left unchanged and counted as deferred.
    Changing it would alter a live business record, and whether that is acceptable is decision 2 in the E13
    document. Deferred contacts are reported, never silently skipped.
    """
    dependent = _dependent_contact_ids(db, organization_id)
    contacts = db.scalars(
        select(Contact).where(Contact.organization_id == organization_id)
    ).all()
    anonymized = 0
    deferred = 0
    for contact in contacts:
        if contact.id in dependent:
            deferred += 1
            continue
        contact.first_name = REDACTED_NAME
        contact.last_name = None
        contact.email = None
        contact.phone = None
        contact.is_active = False
        anonymized += 1
    db.flush()
    return anonymized, deferred


def _anonymize_invitations(
    db: Session,
    organization_id: UUID,
    *,
    now: datetime,
    cutoff: datetime | None = None,
) -> int:
    query = select(TeamInvitation).where(
        TeamInvitation.organization_id == organization_id
    )
    if cutoff is not None:
        query = query.where(TeamInvitation.created_at < cutoff)
    invitations = db.scalars(query).all()
    for invitation in invitations:
        invitation.email = f"redacted-{invitation.id}@{REDACTED_EMAIL_DOMAIN}"
        if invitation.status == "pending":
            # The address is gone, so the invitation must not be accepted for it.
            invitation.status = "revoked"
            invitation.revoked_at = invitation.revoked_at or now
    db.flush()
    return len(invitations)


class PostDeletionVerificationError(PrivacyExecutionError):
    """A deletion ran, but the database or storage does not show the expected result."""


def _require_verified(passed: bool, category_key: str) -> None:
    if not passed:
        # Raised inside the savepoint, so the partial change is rolled back and the request stays open.
        raise PostDeletionVerificationError(f"Verification failed for {category_key}.")


def _execute_category(
    db: Session,
    organization_id: UUID,
    category_key: str,
    *,
    storage: ObjectStorage,
    now: datetime,
    cutoff: datetime | None = None,
) -> _Execution:
    if category_key == DOCUMENTS_CATEGORY:
        count, keys = _delete_documents(db, organization_id, storage, cutoff=cutoff)
        _require_verified(
            _verify_documents(db, organization_id, storage, keys, cutoff=cutoff), category_key
        )
        return _Execution(OUTCOME_DELETED, count)
    if category_key == INVITATIONS_CATEGORY:
        count = _anonymize_invitations(db, organization_id, now=now, cutoff=cutoff)
        _require_verified(_verify_invitations(db, organization_id, cutoff=cutoff), category_key)
        return _Execution(OUTCOME_ANONYMIZED, count)
    if category_key == CONTACTS_CATEGORY:
        count, deferred = _anonymize_contacts(db, organization_id)
        _require_verified(_verify_contacts(db, organization_id), category_key)
        return _Execution(
            OUTCOME_ANONYMIZED_PARTIAL,
            count,
            deferred,
            (
                "crm.leads",
                "crm.customer_profiles",
                "crm.requirements",
                "crm.deals",
                "crm.follow_ups",
            ),
        )
    return _Execution(OUTCOME_NOT_EXECUTED)


def _execution_record(
    execution: _Execution, reasons: list[str] | None = None
) -> dict[str, Any]:
    record: dict[str, Any] = {"outcome": execution.outcome}
    if execution.outcome != OUTCOME_NOT_EXECUTED:
        record["count"] = execution.count
        # Reached only after the post-deletion check passed.
        record["verified"] = True
    if execution.deferred:
        # Contacts still referenced by live records are left unchanged. Reported, never silent.
        record["deferred_dependent"] = execution.deferred
    if execution.not_changed:
        record["not_changed"] = list(execution.not_changed)
    if reasons:
        record["reasons"] = reasons
    return record


def execute_deletion(
    db: Session,
    request: PrivacyDataRequest,
    *,
    storage: ObjectStorage,
    now: datetime,
) -> None:
    """Run the deletions recorded as eligible. No-op unless the request is awaiting execution."""
    if request.request_type != PrivacyDataRequest.TYPE_DELETION:
        raise InvalidRequestStateError("Only deletion requests are executed here.")
    if request.status != STATUS_ELIGIBILITY_RECORDED:
        return

    decisions: dict[str, dict[str, Any]] = json.loads(request.decisions)
    eligible = sorted(
        key for key, decision in decisions.items() if decision.get("eligible")
    )
    started = record_requested_privacy_event(
        db,
        organization_id=request.organization_id,
        actor_user_id=None,
        action="privacy.deletion.requested",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={"eligible": eligible, "requested_by_user_id": str(request.requested_by_user_id)},
    )
    execution: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, str] = {}
    for key in eligible:
        # Re-check at execution time: a hold placed after the request must still block it.
        current = evaluate_deletion(
            db, organization_id=request.organization_id, category_key=key
        )
        if not current.eligible:
            execution[key] = {
                "outcome": OUTCOME_SKIPPED,
                "reasons": list(current.reasons),
            }
            outcomes[key] = OUTCOME_SKIPPED
            continue
        result = _execute_category(
            db, request.organization_id, key, storage=storage, now=now
        )
        if result.outcome == OUTCOME_NOT_EXECUTED:
            execution[key] = _execution_record(result, [REASON_EXECUTOR_NOT_BUILT])
        else:
            execution[key] = _execution_record(result)
        outcomes[key] = result.outcome

    performed = [key for key in eligible if outcomes[key] in OUTCOMES_PERFORMED]
    if not performed:
        status = STATUS_BLOCKED
    elif all(outcomes[key] in OUTCOMES_FULL for key in eligible):
        status = STATUS_COMPLETED
    else:
        status = STATUS_PARTIALLY_COMPLETED

    request.attempt_count += 1
    request.processed_at = now
    request.status = status
    request.execution = json.dumps(execution, sort_keys=True)
    record_completed_privacy_event(
        db,
        requested=started,
        action=f"privacy.deletion.{status}",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={"status": status, "execution": execution},
    )
    db.flush()


def enforce_retention(
    db: Session,
    *,
    organization_id: UUID,
    storage: ObjectStorage,
    now: datetime,
) -> dict[str, dict[str, Any]]:
    """Apply the organization's retention periods to the enforced categories.

    Each category is checked against legal holds before anything is removed. A category with a
    period but no enforcer is reported as not enforced, never as applied.
    """
    report: dict[str, dict[str, Any]] = {}
    configured = sorted(
        db.scalars(
            select(RetentionPolicy.category_key)
            .where(RetentionPolicy.organization_id == organization_id)
            .distinct()
        ).all()
    )
    for key in configured:
        policy = current_retention(
            db, organization_id=organization_id, category_key=key
        )
        if policy is None or policy.retention_days is None:
            report[key] = {"outcome": "no_period"}
            continue
        if key not in RETENTION_ENFORCED:
            report[key] = {
                "outcome": "not_enforced",
                "reasons": [REASON_RETENTION_NOT_ENFORCED],
            }
            continue

        decision = evaluate_deletion(
            db, organization_id=organization_id, category_key=key
        )
        if not decision.eligible:
            report[key] = {
                "outcome": OUTCOME_SKIPPED,
                "reasons": list(decision.reasons),
            }
            record_requested_privacy_event(
                db,
                organization_id=organization_id,
                actor_user_id=None,
                action="privacy.retention.skipped",
                resource_type="retention_policy",
                resource_id=key,
                metadata=report[key],
            )
            continue

        cutoff = now - timedelta(days=policy.retention_days)
        started = record_requested_privacy_event(
            db,
            organization_id=organization_id,
            actor_user_id=None,
            action="privacy.retention.requested",
            resource_type="retention_policy",
            resource_id=key,
            metadata={"cutoff": cutoff.isoformat(), "retention_days": policy.retention_days},
        )
        result = _execute_category(
            db, organization_id, key, storage=storage, now=now, cutoff=cutoff
        )
        record = _execution_record(result)
        record["cutoff"] = cutoff.isoformat()
        record["retention_days"] = policy.retention_days
        report[key] = record
        record_completed_privacy_event(
            db,
            requested=started,
            action="privacy.retention.enforced",
            resource_type="retention_policy",
            resource_id=key,
            metadata=record,
        )
    db.flush()
    return report


def _load_request(
    db: Session, *, organization_id: UUID, request_id: UUID
) -> PrivacyDataRequest:
    request = db.scalar(
        select(PrivacyDataRequest).where(
            PrivacyDataRequest.id == request_id,
            PrivacyDataRequest.organization_id == organization_id,
        )
    )
    if request is None:
        raise PrivacyRequestNotFoundError("Privacy request not found.")
    return request


def process_privacy_request(db: Session, event: OutboxEvent) -> None:
    """Outbox handler. Runs in a savepoint; a raised error rolls back the processing and retries."""
    settings = get_settings()
    request_id = UUID(str(event.payload["request_id"]))
    request = _load_request(
        db, organization_id=event.organization_id, request_id=request_id
    )
    now = datetime.now(UTC)
    storage = get_object_storage()
    if request.request_type == PrivacyDataRequest.TYPE_EXPORT:
        generate_export(
            db,
            request,
            storage=storage,
            now=now,
            max_bytes=settings.privacy_export_max_bytes,
            ttl=timedelta(days=settings.privacy_export_ttl_days),
        )
    else:
        execute_deletion(db, request, storage=storage, now=now)


def register_privacy_handlers() -> None:
    register_handler(PRIVACY_PROCESS_EVENT_TYPE, process_privacy_request)


def _delete_export_object(storage: ObjectStorage, key: str) -> None:
    try:
        storage.delete(key)
    except ObjectNotFoundError:
        pass


def expire_request_export(
    db: Session, request: PrivacyDataRequest, *, storage: ObjectStorage, now: datetime
) -> bool:
    """Expire one ready export and remove its object. Returns True when it expired now."""
    stored_key = request.artifact_reference
    before = request.status
    expire_export_if_due(db, request=request, now=now)
    if (
        before in {STATUS_READY, STATUS_READY_PARTIAL}
        and request.status == STATUS_EXPIRED
    ):
        started = record_requested_privacy_event(
            db,
            organization_id=request.organization_id,
            actor_user_id=None,
            action="privacy.export.expiry.requested",
            resource_type="privacy_request",
            resource_id=str(request.id),
            metadata={},
        )
        if stored_key:
            _delete_export_object(storage, stored_key)
        record_completed_privacy_event(
            db,
            requested=started,
            action="privacy.export.expired",
            resource_type="privacy_request",
            resource_id=str(request.id),
            metadata={},
        )
        db.flush()
        return True
    return False


def open_export(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
    storage: ObjectStorage,
    now: datetime,
) -> BinaryIO:
    """Open a ready export for download. Audited. Raises when unavailable or expired."""
    request = _load_request(db, organization_id=organization_id, request_id=request_id)
    if request.request_type != PrivacyDataRequest.TYPE_EXPORT:
        raise ExportUnavailableError("Only export requests have artifacts.")

    if expire_request_export(db, request, storage=storage, now=now):
        db.flush()
        raise ExportUnavailableError("This export has expired.")
    if request.status == STATUS_EXPIRED:
        raise ExportUnavailableError("This export has expired.")
    if (
        request.status not in {STATUS_READY, STATUS_READY_PARTIAL}
        or not request.artifact_reference
    ):
        raise ExportUnavailableError("This export is not ready.")

    record_requested_privacy_event(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="privacy.export.downloaded",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={"status": request.status},
    )
    try:
        handle = storage.open_read(request.artifact_reference)
    except ObjectNotFoundError as error:
        raise ExportUnavailableError("This export is not available.") from error

    db.flush()
    return handle
