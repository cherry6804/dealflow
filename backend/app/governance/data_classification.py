"""Data classification register for retention, export and deletion (DFR1-050).

Every category the privacy controls can act on is listed here with its sensitivity, its
retention treatment, and whether a producer exists in the codebase today. A category
with ``producer_exists=False`` must not be reported as covered by export or deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Sensitivity(str, Enum):
    STANDARD = "standard"
    PERSONAL = "personal"
    SENSITIVE_CONTENT = "sensitive_content"
    SECRET_REFERENCE = "secret_reference"


class RetentionTreatment(str, Enum):
    """How a category may be retained or removed."""

    ORGANIZATION_CONFIGURABLE = "organization_configurable"
    MANDATORY_RECORD = "mandatory_record"
    NEVER_DELETE_BY_CUSTOMER = "never_delete_by_customer"


@dataclass(frozen=True)
class DataCategory:
    key: str
    label: str
    sensitivity: Sensitivity
    retention: RetentionTreatment
    producer_exists: bool
    note: str = ""


CATEGORIES: tuple[DataCategory, ...] = (
    DataCategory("crm.contacts", "Contacts", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.leads", "Leads", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.customer_profiles", "Customer profiles", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.requirements", "Customer requirements", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.deals", "Deals and stage history", Sensitivity.STANDARD, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.follow_ups", "Follow-ups and activities", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("documents.files", "Uploaded documents", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Stored in private storage; external object deletion is not implemented."),
    DataCategory("billing.records", "Billing and reconciliation records", Sensitivity.STANDARD, RetentionTreatment.MANDATORY_RECORD, True,
                 "Financial recordkeeping. Never deleted by a customer request."),
    DataCategory("audit.events", "Audit events", Sensitivity.STANDARD, RetentionTreatment.MANDATORY_RECORD, True,
                 "Security and governance records. Never deleted by a customer request."),
    DataCategory("team.invitations", "Team invitations", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("messaging.email_outbox", "Outbound email (encrypted payloads)", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("messaging.conversations", "Conversations and messages", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "No conversation producer exists. Channel gateway is not built."),
    DataCategory("voice.call_records", "Voice call records", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "Voice (DFR1-027) is not built."),
    DataCategory("voice.transcripts", "Call transcripts and recordings", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "Voice transcription (DFR1-028) is not built."),
    DataCategory("ai.prompts_and_responses", "AI prompts and responses", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "AI gateway (DFR1-015) is not built."),
    DataCategory("ai.embeddings", "Embeddings and knowledge index", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "Knowledge ingestion (DFR1-016) is not built."),
    DataCategory("ai.usage", "AI usage ledger", Sensitivity.STANDARD, RetentionTreatment.MANDATORY_RECORD, True,
                 "Usage ledger (DFR1-017). Retained as a financial record."),
    DataCategory("ai.execution_traces", "AI execution traces", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "Agent runtime (DFR1-019) is not built."),
    DataCategory("security.credentials", "Provider credentials and secret references", Sensitivity.SECRET_REFERENCE, RetentionTreatment.NEVER_DELETE_BY_CUSTOMER, False,
                 "Secrets are never exported. No provider connection exists yet."),
)

CATEGORY_BY_KEY: dict[str, DataCategory] = {category.key: category for category in CATEGORIES}


def is_customer_deletable(category: DataCategory) -> bool:
    """A category can be removed on request only when its treatment allows it."""
    return category.retention is RetentionTreatment.ORGANIZATION_CONFIGURABLE
