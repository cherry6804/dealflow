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
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.activity import Activity
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.channel_policy import ContactDoNotDisturb
from app.db.models.contact import Contact
from app.db.models.contact_consent import ContactConsentRecord
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
from app.db.models.import_batch import ImportBatch
from app.db.models.knowledge_chunk import KnowledgeChunk
from app.db.models.lead import Lead
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationPreference
from app.db.models.outbox_event import OutboxEvent
from app.db.models.payment_milestone import PaymentMilestone
from app.db.models.privacy_records import PrivacyDataRequest, RetentionPolicy
from app.db.models.property import Property
from app.db.models.referral import Referral
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.db.models.requirement_property_shortlist import RequirementPropertyShortlist
from app.db.models.requirement_shortlist_event import RequirementShortlistEvent
from app.db.models.site_visit import SiteVisit
from app.db.models.team_invitation import TeamInvitation
from app.db.models.team_member_removal import TeamMemberRemoval
from app.governance.data_classification import CATEGORIES, CATEGORY_BY_KEY
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
from app.governance.privacy_derived import (
    DERIVED_EXPORTERS,
    DERIVED_SUB_RECORD_EXPORTERS,
    PRIVACY_LIMITATIONS,
    RETAINED_PERSONAL_DATA_HISTORY,
    RETAINED_RECORDS,
    RULE_CATEGORIES,
    apply_clearing,
    kept_fields,
    pending_clearing,
)
from app.governance.table_inventory import DISPOSITION_EXPORTED, TABLE_INVENTORY
from app.imports.storage import delete_stored_upload
from app.knowledge.service import remove_document_chunks
from app.multimodal.review import remove_document_review
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
LEADS_CATEGORY = "crm.leads"
FOLLOW_UPS_CATEGORY = "crm.follow_ups"
PROFILES_CATEGORY = "crm.customer_profiles"
REQUIREMENTS_CATEGORY = "crm.requirements"
DEALS_CATEGORY = "crm.deals"
PROPERTIES_CATEGORY = "crm.properties"
REFERRALS_CATEGORY = "crm.referrals"
SITE_VISITS_CATEGORY = "crm.site_visits"
MATCHING_CATEGORY = "crm.requirement_matching"
NOTIFICATIONS_CATEGORY = "messaging.notifications"
IMPORT_MEMBER_PREFIX = "imports"
AI_EMBEDDINGS_CATEGORY = "ai.embeddings"

# CRM categories whose approved free-text fields are cleared by a deletion (decision B).
FREE_TEXT_CATEGORIES: frozenset[str] = RULE_CATEGORIES

# Financial and contractual fields that a deletion keeps (decision B and G). Exported, never changed.
PRESERVED_FINANCIAL_FIELDS: tuple[str, ...] = (
    "payment_milestones.notes",
    "payment_milestones.payment_reference",
    "deal_commissions.terms",
    "deal_commissions.payment_reference",
)

# Shown in place of a required text field that is cleared. Same placeholder as a redacted contact name.
FREE_TEXT_PLACEHOLDER = REDACTED_NAME

REASON_NO_FREE_TEXT = "no_free_text_fields"
REASON_STORED_OBJECT_MISSING = "stored_object_missing"
REASON_STORED_OBJECT_CHECKSUM = "stored_object_checksum_mismatch"
REASON_EXPORT_SIZE_LIMIT = "export_size_limit_exceeded"
REASON_ENCRYPTED_PAYLOAD = "encrypted_payload_not_exportable"
REASON_RETENTION_NOT_ENFORCED = "retention_enforcement_not_built"

OUTCOME_DELETED = "deleted"
OUTCOME_DELETED_PARTIAL = "deleted_partial"
OUTCOME_ANONYMIZED = "anonymized"
OUTCOME_ANONYMIZED_PARTIAL = "anonymized_partial"
OUTCOME_NOT_EXECUTED = "not_executed"
OUTCOME_SKIPPED = "skipped"

# Only these outcomes complete a category. Anything partial keeps the request partial.
OUTCOMES_FULL = frozenset({OUTCOME_DELETED, OUTCOME_ANONYMIZED})
OUTCOMES_PERFORMED = frozenset(
    {OUTCOME_DELETED, OUTCOME_DELETED_PARTIAL, OUTCOME_ANONYMIZED, OUTCOME_ANONYMIZED_PARTIAL}
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
    """Export every document and import attachment with its stored file, or none of them."""
    documents = db.scalars(
        select(Document)
        .where(Document.organization_id == organization_id)
        .order_by(Document.created_at, Document.id)
    ).all()
    batches = _import_attachment_batches(db, organization_id)
    declared = sum(document.file_size_bytes or 0 for document in documents) + sum(
        batch.file_size_bytes or 0 for batch in batches
    )
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
                "kind": "document",
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

    for batch in batches:
        content = _read_import_attachment(batch, max_bytes=max_bytes - total)
        total += len(content)
        member = f"{IMPORT_MEMBER_PREFIX}/{batch.id}{_safe_extension(Path(batch.source_filename).suffix)}"
        members[member] = content
        rows.append(
            {
                "kind": "import_attachment",
                "id": str(batch.id),
                "original_filename": batch.source_filename,
                "source_format": batch.source_format,
                "content_type": batch.content_type,
                "file_size_bytes": batch.file_size_bytes,
                "status": batch.status,
                "created_at": _iso(batch.created_at),
                "archive_path": member,
            }
        )
    return rows, members


def _import_attachment_batches(db: Session, organization_id: UUID, *, cutoff: datetime | None = None) -> list[ImportBatch]:
    """Import batches whose uploaded file is still stored."""
    query = (
        select(ImportBatch)
        .where(ImportBatch.organization_id == organization_id, ImportBatch.storage_key.is_not(None))
        .order_by(ImportBatch.created_at, ImportBatch.id)
    )
    if cutoff is not None:
        query = query.where(ImportBatch.created_at < cutoff)
    return list(db.scalars(query).all())


def _import_upload_path(storage_key: str) -> Path:
    """Resolve an upload key inside the upload root. Any other path is refused."""
    root = get_settings().upload_storage_dir.resolve()
    candidate = (root / storage_key).resolve()
    if candidate == root or root not in candidate.parents:
        raise CategoryNotExportedError(REASON_STORED_OBJECT_MISSING)
    return candidate


def _read_import_attachment(batch: ImportBatch, *, max_bytes: int) -> bytes:
    """Read one stored upload. A missing file or a size mismatch excludes the whole category."""
    if not batch.storage_key:
        raise CategoryNotExportedError(REASON_STORED_OBJECT_MISSING)
    path = _import_upload_path(batch.storage_key)
    try:
        size = path.stat().st_size
    except FileNotFoundError as error:
        raise CategoryNotExportedError(REASON_STORED_OBJECT_MISSING) from error
    if size > max_bytes:
        raise CategoryNotExportedError(REASON_EXPORT_SIZE_LIMIT)
    content = path.read_bytes()
    if batch.file_size_bytes is not None and batch.file_size_bytes != len(content):
        raise CategoryNotExportedError(REASON_STORED_OBJECT_CHECKSUM)
    return content


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


def _id(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _export_properties(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Properties with their source and owner references as identifiers. Contact details are exported under contacts."""
    rows = db.scalars(
        select(Property).where(Property.organization_id == organization_id).order_by(Property.created_at, Property.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "status": row.status,
            "transaction_type": row.transaction_type,
            "price": row.price,
            "currency": row.currency,
            "rent": row.rent,
            "security_deposit": row.security_deposit,
            "maintenance_charge": row.maintenance_charge,
            "address_line_1": row.address_line_1,
            "address_line_2": row.address_line_2,
            "locality": row.locality,
            "city": row.city,
            "state": row.state,
            "postal_code": row.postal_code,
            "property_type": row.property_type,
            "bhk": row.bhk,
            "built_up_area": row.built_up_area,
            "carpet_area": row.carpet_area,
            "floor_number": row.floor_number,
            "total_floors": row.total_floors,
            "source_contact_id": _id(row.source_contact_id),
            "owner_contact_id": _id(row.owner_contact_id),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_referrals(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Referral).where(Referral.organization_id == organization_id).order_by(Referral.created_at, Referral.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_profile_id": _id(row.customer_profile_id),
            "referrer_contact_id": _id(row.referrer_contact_id),
            "deal_id": _id(row.deal_id),
            "referral_name": row.referral_name,
            "referral_phone": row.referral_phone,
            "referral_email": row.referral_email,
            "status": row.status,
            "notes": row.notes,
            "is_active": row.is_active,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_site_visits(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(SiteVisit).where(SiteVisit.organization_id == organization_id).order_by(SiteVisit.scheduled_at, SiteVisit.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "property_id": str(row.property_id),
            "lead_id": _id(row.lead_id),
            "customer_profile_id": _id(row.customer_profile_id),
            "owner_user_id": str(row.owner_user_id),
            "scheduled_at": _iso(row.scheduled_at),
            "ends_at": _iso(row.ends_at),
            "status": row.status,
            "outcome": row.outcome,
            "notes": row.notes,
            "feedback": row.feedback,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_match_runs(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Matching runs for requirements. Results, shortlists and shortlist events are sub-records."""
    rows = db.scalars(
        select(RequirementMatchRun)
        .where(RequirementMatchRun.organization_id == organization_id)
        .order_by(RequirementMatchRun.created_at, RequirementMatchRun.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "actor_id": str(row.actor_id),
            "criteria_snapshot": row.criteria_snapshot,
            "ruleset_version": row.ruleset_version,
            "input_hash": row.input_hash,
            "total_candidates": row.total_candidates,
            "matched_candidates": row.matched_candidates,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_match_results(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(RequirementMatchRunResult)
        .where(RequirementMatchRunResult.organization_id == organization_id)
        .order_by(RequirementMatchRunResult.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "match_run_id": str(row.match_run_id),
            "property_id": str(row.property_id),
            "overall_match": row.overall_match,
            "rank": row.rank,
            "eligibility": row.eligibility,
            "ranking_basis": row.ranking_basis,
            "property_snapshot": row.property_snapshot,
            "criteria_results_snapshot": row.criteria_results_snapshot,
        }
        for row in rows
    ]


def _export_shortlists(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(RequirementPropertyShortlist)
        .where(RequirementPropertyShortlist.organization_id == organization_id)
        .order_by(RequirementPropertyShortlist.created_at, RequirementPropertyShortlist.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "property_id": str(row.property_id),
            "created_by_user_id": str(row.created_by_user_id),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_shortlist_events(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(RequirementShortlistEvent)
        .where(RequirementShortlistEvent.organization_id == organization_id)
        .order_by(RequirementShortlistEvent.created_at, RequirementShortlistEvent.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "property_id": str(row.property_id),
            "actor_id": str(row.actor_id),
            "event_type": row.event_type,
            "property_snapshot": row.property_snapshot,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_notifications(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Notification).where(Notification.organization_id == organization_id).order_by(Notification.created_at, Notification.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "recipient_user_id": str(row.recipient_user_id),
            "event_type": row.event_type,
            "title": row.title,
            "message": row.message,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "created_at": _iso(row.created_at),
            "read_at": _iso(row.read_at),
        }
        for row in rows
    ]


def _export_notification_preferences(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(NotificationPreference).where(NotificationPreference.organization_id == organization_id)
    ).all()
    return [
        {
            "id": str(row.id),
            "user_id": str(row.user_id),
            "enabled": row.enabled,
            "follow_ups_enabled": row.follow_ups_enabled,
            "deals_enabled": row.deals_enabled,
            "site_visits_enabled": row.site_visits_enabled,
            "leads_enabled": row.leads_enabled,
            "automation_enabled": row.automation_enabled,
        }
        for row in rows
    ]


def _export_consent_records(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ContactConsentRecord)
        .where(ContactConsentRecord.organization_id == organization_id)
        .order_by(ContactConsentRecord.recorded_at, ContactConsentRecord.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "contact_id": str(row.contact_id),
            "channel": row.channel,
            "purpose": row.purpose,
            "scope": row.scope,
            "status": row.status,
            "policy_version": row.policy_version,
            "source": row.source,
            "evidence_note": row.evidence_note,
            "expires_at": _iso(row.expires_at),
            "recorded_at": _iso(row.recorded_at),
        }
        for row in rows
    ]


def _export_do_not_disturb(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ContactDoNotDisturb).where(ContactDoNotDisturb.organization_id == organization_id)
    ).all()
    return [
        {
            "id": str(row.id),
            "contact_id": str(row.contact_id),
            "set_by_user_id": str(row.set_by_user_id),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _export_membership_removals(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(TeamMemberRemoval)
        .where(TeamMemberRemoval.organization_id == organization_id)
        .order_by(TeamMemberRemoval.created_at, TeamMemberRemoval.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "membership_id": str(row.membership_id),
            "target_user_id": str(row.target_user_id),
            "actor_user_id": str(row.actor_user_id),
            "reason": row.reason,
            "seat_outcome": row.seat_outcome,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


EXPORTERS: dict[str, Callable[[Session, UUID], list[dict[str, Any]]]] = {
    CONTACTS_CATEGORY: _export_contacts,
    LEADS_CATEGORY: _export_leads,
    FOLLOW_UPS_CATEGORY: _export_follow_ups,
    PROFILES_CATEGORY: _export_customer_profiles,
    REQUIREMENTS_CATEGORY: _export_requirements,
    DEALS_CATEGORY: _export_deals,
    PROPERTIES_CATEGORY: _export_properties,
    REFERRALS_CATEGORY: _export_referrals,
    SITE_VISITS_CATEGORY: _export_site_visits,
    MATCHING_CATEGORY: _export_match_runs,
    NOTIFICATIONS_CATEGORY: _export_notifications,
    "ai.usage": _export_ai_usage,
    INVITATIONS_CATEGORY: _export_invitations,
}

# Sub-records are exported under their parent category. Each list is part of that category.
SUB_RECORD_EXPORTERS: dict[str, dict[str, Callable[[Session, UUID], list[dict[str, Any]]]]] = {
    REQUIREMENTS_CATEGORY: {
        "requirement_locations": _export_requirement_locations,
        "requirement_property_preferences": _export_requirement_property_preferences,
        "requirement_parking_preferences": _export_requirement_parking_preferences,
        "requirement_history": _export_requirement_history,
    },
    DEALS_CATEGORY: {
        "negotiations": _export_deal_negotiations,
        "negotiation_history": _export_deal_negotiation_history,
        "stage_history": _export_deal_stage_history,
    },
    FOLLOW_UPS_CATEGORY: {
        "activities": _export_activities,
    },
    MATCHING_CATEGORY: {
        "results": _export_match_results,
        "shortlists": _export_shortlists,
        "shortlist_events": _export_shortlist_events,
    },
    NOTIFICATIONS_CATEGORY: {
        "preferences": _export_notification_preferences,
    },
    CONTACTS_CATEGORY: {
        "consent_records": _export_consent_records,
        "do_not_disturb": _export_do_not_disturb,
    },
    INVITATIONS_CATEGORY: {
        "membership_removals": _export_membership_removals,
    },
}

# Derived and operational records (privacy_derived). Merged here so one registry drives the export.
EXPORTERS.update(DERIVED_EXPORTERS)
for _category, _subs in DERIVED_SUB_RECORD_EXPORTERS.items():
    SUB_RECORD_EXPORTERS.setdefault(_category, {}).update(_subs)

# Organization-owned tables that no export covers. Every artifact lists them, so none is left out silently.
NOT_COVERED_TABLES: tuple[dict[str, str], ...] = tuple(
    {"table": table, "classification": entry.disposition, "reason": entry.reason or entry.category or ""}
    for table, entry in TABLE_INVENTORY.items()
    if entry.disposition != DISPOSITION_EXPORTED
)

# Data that belongs to SIBVO. Dealsflo does not change it. Every export states it and the route to use.
SIBVO_OWNED_CATEGORIES: tuple[dict[str, str], ...] = (
    {"category": "Organization memberships and roles", "tables": "organization_memberships, membership_roles", "owner": "SIBVO (decision D6)"},
    {"category": "Subscriptions, plans and entitlements", "tables": "subscriptions, plans, plan_entitlements, organization_entitlement_snapshots", "owner": "SIBVO (decision D6)"},
    {"category": "Identity links", "tables": "sibvo_identity_links, sibvo_organization_links", "owner": "SIBVO (decision D6)"},
    {"category": "Platform billing records", "tables": "billing_reconciliation_records, billing_webhook_events", "owner": "SIBVO (decision F). Export excluded by decision D3."},
    {"category": "User accounts", "tables": "users", "owner": "SIBVO (decision F)"},
)
SIBVO_PRIVACY_ROUTE = (
    "Requests about identity, organization membership, subscriptions, plans and platform billing are answered by "
    "SIBVO's platform privacy process. Dealsflo does not change these records. See "
    "docs/architecture/sibvo-dealsflo-sso-contract.md."
)


def _not_implemented_categories() -> list[dict[str, str]]:
    """Categories whose producer does not exist yet. Listed so no export implies they were checked."""
    return [
        {"category_key": category.key, "label": category.label, "reason": category.note or "Producer not built."}
        for category in CATEGORIES
        if not category.producer_exists
    ]


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


def request_deletion_execution(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
) -> PrivacyDataRequest:
    """Start execution of a recorded deletion. The explicit, audited step that precedes any destructive work.

    Only a request in its eligibility-recorded state can start. Holds are checked again by the worker before each
    category runs, so a hold placed after this step still blocks it. Repeating the call queues one event, because
    the processing event carries an idempotency key.
    """
    request = _load_request(db, organization_id=organization_id, request_id=request_id)
    if request.request_type != PrivacyDataRequest.TYPE_DELETION:
        raise InvalidRequestStateError("Only deletion requests are executed.")
    if request.status != STATUS_ELIGIBILITY_RECORDED:
        raise InvalidRequestStateError(f"Deletion is {request.status} and cannot be executed.")
    record_requested_privacy_event(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action="privacy.deletion.execution_requested",
        resource_type="privacy_request",
        resource_id=str(request.id),
        metadata={"categories": json.loads(request.categories)},
    )
    enqueue_processing(db, request)
    db.flush()
    return request


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
            # Categories whose producers are not built. Never reported as checked.
            "not_implemented_categories": _not_implemented_categories(),
            # Data owned by SIBVO, with the route for requests about it.
            "sibvo_owned": [dict(item) for item in SIBVO_OWNED_CATEGORIES],
            "sibvo_privacy_route": SIBVO_PRIVACY_ROUTE,
            # What this export and its deletions do not cover, stated where a reader of the artifact will see it.
            "limitations": [dict(item) for item in PRIVACY_LIMITATIONS],
            # Personal-data history kept because it is append-only or mandatory evidence.
            "retained_personal_data_history": [dict(item) for item in RETAINED_PERSONAL_DATA_HISTORY],
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
        remove_document_chunks(db, organization_id=organization_id, document_id=document.id)
        remove_document_review(db, organization_id=organization_id, document_id=document.id)
        db.delete(document)
    # Rows first, then objects. If an object cannot be removed, the savepoint rolls the rows back, so no
    # row is left pointing at an object that was already deleted. A missing object counts as removed.
    db.flush()
    for key in keys:
        try:
            storage.delete(key)
        except ObjectNotFoundError:
            pass
    return len(documents), keys


def _import_batches_to_clear(db: Session, organization_id: UUID, *, cutoff: datetime | None = None) -> list[ImportBatch]:
    """Batches that still hold personal content: a stored file, a file name, or a per-row error summary.

    A batch whose file was removed earlier can still hold a name or error text, so it is included.
    """
    query = (
        select(ImportBatch)
        .where(
            ImportBatch.organization_id == organization_id,
            or_(
                ImportBatch.storage_key.is_not(None),
                ImportBatch.error_summary.is_not(None),
                ImportBatch.source_filename != FREE_TEXT_PLACEHOLDER,
            ),
        )
        .order_by(ImportBatch.created_at, ImportBatch.id)
    )
    if cutoff is not None:
        query = query.where(ImportBatch.created_at < cutoff)
    return list(db.scalars(query).all())


def _delete_import_attachments(
    db: Session,
    organization_id: UUID,
    *,
    cutoff: datetime | None = None,
) -> tuple[int, list[str]]:
    """Remove stored import uploads and the personal text on each batch.

    The batch row is kept with its technical fields only: identifiers, format, counts, status and timestamps.
    Imported contacts reference the row with RESTRICT, so it cannot be removed.
    """
    batches = _import_batches_to_clear(db, organization_id, cutoff=cutoff)
    keys: list[str] = []
    for batch in batches:
        if batch.storage_key:
            keys.append(batch.storage_key)
        batch.storage_key = None
        batch.storage_backend = None
        batch.source_filename = FREE_TEXT_PLACEHOLDER
        batch.error_summary = None
    db.flush()
    for key in keys:
        # The same rule as the upload path: a key outside the root raises and rolls the change back.
        delete_stored_upload(key)
    return len(batches), keys


def _verify_import_attachments(
    db: Session,
    organization_id: UUID,
    keys: list[str],
    *,
    cutoff: datetime | None,
) -> bool:
    if _import_batches_to_clear(db, organization_id, cutoff=cutoff):
        return False
    return not any(_import_upload_path(key).exists() for key in keys if key)


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
    anonymized_ids: list[UUID] = []
    for contact in contacts:
        if contact.id in dependent:
            deferred += 1
            continue
        contact.first_name = REDACTED_NAME
        contact.last_name = None
        contact.email = None
        contact.phone = None
        contact.is_active = False
        anonymized_ids.append(contact.id)
        anonymized += 1
    if anonymized_ids:
        # The consent evidence note is free text written about the same person, so it is cleared with the contact.
        # The consent decision itself is kept as evidence.
        db.execute(
            update(ContactConsentRecord)
            .where(
                ContactConsentRecord.organization_id == organization_id,
                ContactConsentRecord.contact_id.in_(anonymized_ids),
                ContactConsentRecord.evidence_note.is_not(None),
            )
            .values(evidence_note=None)
        )
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
        attachments, attachment_keys = _delete_import_attachments(db, organization_id, cutoff=cutoff)
        _require_verified(
            _verify_documents(db, organization_id, storage, keys, cutoff=cutoff)
            and _verify_import_attachments(db, organization_id, attachment_keys, cutoff=cutoff),
            category_key,
        )
        if attachments:
            # The file is gone, but the batch row stays because imported contacts reference it. Never reported as full.
            return _Execution(
                OUTCOME_DELETED_PARTIAL,
                count + attachments,
                0,
                ("import_batches: rows kept because imported contacts reference them",),
            )
        return _Execution(OUTCOME_DELETED, count)
    if category_key == AI_EMBEDDINGS_CATEGORY:
        return _delete_knowledge_chunks(db, organization_id)
    if category_key in FREE_TEXT_CATEGORIES:
        return _clear_crm_free_text(db, organization_id, category_key)
    if category_key == REQUIREMENTS_CATEGORY:
        return _clear_requirement_places(db, organization_id)
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


def _clear_crm_free_text(db: Session, organization_id: UUID, category_key: str) -> _Execution:
    """Clear approved free-text fields and keep every structural record. Verified before it reports success.

    The fields are defined per model in ``privacy_derived.CLEARING_RULES``. The same check runs for every category.
    """
    changed = apply_clearing(db, organization_id, category_key)
    _require_verified(not pending_clearing(db, organization_id, category_key), category_key)
    return _Execution(
        OUTCOME_ANONYMIZED_PARTIAL,
        changed,
        0,
        (
            *(PRESERVED_FINANCIAL_FIELDS if category_key == DEALS_CATEGORY else ()),
            *kept_fields(category_key),
            *RETAINED_RECORDS.get(category_key, ()),
            "contacts: identity is handled by the contacts category; linked records are kept",
        ),
    )


def _requirement_places_remaining(db: Session, organization_id: UUID) -> bool:
    """True while any location value, current or inside a history snapshot, still holds a real place name."""
    if db.scalar(
        select(func.count(CustomerRequirementLocation.id)).where(
            CustomerRequirementLocation.organization_id == organization_id,
            or_(
                CustomerRequirementLocation.city != FREE_TEXT_PLACEHOLDER,
                CustomerRequirementLocation.locality != FREE_TEXT_PLACEHOLDER,
            ),
        )
    ):
        return True
    for history in db.scalars(
        select(CustomerRequirementHistory).where(CustomerRequirementHistory.organization_id == organization_id)
    ).all():
        locations = history.snapshot.get("locations") if isinstance(history.snapshot, dict) else None
        for entry in locations or []:
            if any(entry.get(name) not in (None, FREE_TEXT_PLACEHOLDER) for name in ("city", "locality")):
                return True
    return False


def _clear_requirement_places(db: Session, organization_id: UUID) -> _Execution:
    """Replace the place names a customer asked for. These are personal preferences once linked to a customer.

    Kept: the requirement's business terms (status, budget, transaction type), the property and parking codes,
    and the history's version, change type and timestamps. Only city and locality values are replaced.
    """
    changed = 0
    for location in db.scalars(
        select(CustomerRequirementLocation).where(CustomerRequirementLocation.organization_id == organization_id)
    ).all():
        if location.city != FREE_TEXT_PLACEHOLDER or location.locality != FREE_TEXT_PLACEHOLDER:
            location.city = FREE_TEXT_PLACEHOLDER
            location.locality = FREE_TEXT_PLACEHOLDER
            changed += 1
    for history in db.scalars(
        select(CustomerRequirementHistory).where(CustomerRequirementHistory.organization_id == organization_id)
    ).all():
        snapshot = history.snapshot
        locations = snapshot.get("locations") if isinstance(snapshot, dict) else None
        if not locations:
            continue
        replaced = []
        for entry in locations:
            updated = dict(entry)
            for name in ("city", "locality"):
                if name in updated:
                    updated[name] = FREE_TEXT_PLACEHOLDER
            replaced.append(updated)
        if replaced != locations:
            history.snapshot = {**snapshot, "locations": replaced}
            changed += 1
    db.flush()
    _require_verified(not _requirement_places_remaining(db, organization_id), REQUIREMENTS_CATEGORY)
    return _Execution(
        OUTCOME_ANONYMIZED_PARTIAL,
        changed,
        0,
        (
            "customer_requirements: status, budget and transaction type kept as business terms",
            "customer_requirement_property_preferences, customer_requirement_possession_parking_preferences: codes kept",
            "customer_requirement_history: version, change type and timestamps kept; location values replaced",
        ),
    )


def _delete_knowledge_chunks(db: Session, organization_id: UUID) -> _Execution:
    """Remove derived knowledge chunks. They are copies of document text and are rebuilt from the source document."""
    chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.organization_id == organization_id)).all()
    for chunk in chunks:
        db.delete(chunk)
    db.flush()
    remaining = db.scalar(
        select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.organization_id == organization_id)
    )
    _require_verified(remaining == 0, AI_EMBEDDINGS_CATEGORY)
    return _Execution(OUTCOME_DELETED, len(chunks))


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
            reasons = list(result.not_changed) or [REASON_EXECUTOR_NOT_BUILT]
            execution[key] = _execution_record(result, reasons)
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
            metadata={
                "cutoff": cutoff.isoformat(),
                "retention_days": policy.retention_days,
                "policy_version": policy.version,
            },
        )
        result = _execute_category(
            db, organization_id, key, storage=storage, now=now, cutoff=cutoff
        )
        record = _execution_record(result)
        record["cutoff"] = cutoff.isoformat()
        record["retention_days"] = policy.retention_days
        record["policy_version"] = policy.version
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
