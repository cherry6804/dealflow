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
    # False when rows are not tied to one organization. Such rows cannot be exported or deleted
    # for a single organization, so they are reported as not organization-owned instead.
    organization_owned: bool = True


CATEGORIES: tuple[DataCategory, ...] = (
    DataCategory("crm.contacts", "Contacts", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.leads", "Leads", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.customer_profiles", "Customer profiles", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.requirements", "Customer requirements", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.deals", "Deals and stage history", Sensitivity.STANDARD, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.follow_ups", "Follow-ups and activities", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.properties", "Properties and their source and owner references", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Owner and source contacts are exported as identifiers. Their details are exported under contacts."),
    DataCategory("crm.referrals", "Referrals", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Referred third-party contact details."),
    DataCategory("crm.site_visits", "Site visits, notes and feedback", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("crm.requirement_matching", "Requirement matching runs, results and shortlists", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Derived matches for one customer requirement."),
    DataCategory("documents.files", "Uploaded documents and import attachments", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Stored in private storage. Import attachments are stored under the upload root and are covered by the same policy."),
    DataCategory("messaging.notifications", "In-app notifications and preferences", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Notification text can name customers."),
    DataCategory("billing.records", "Billing and reconciliation records", Sensitivity.STANDARD, RetentionTreatment.MANDATORY_RECORD, True,
                 "Financial recordkeeping. Never deleted by a customer request."),
    DataCategory("audit.events", "Audit events", Sensitivity.STANDARD, RetentionTreatment.MANDATORY_RECORD, True,
                 "Security and governance records. Never deleted by a customer request."),
    DataCategory("team.invitations", "Team invitations", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True),
    DataCategory("messaging.email_outbox", "Platform email outbox (encrypted payloads)", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Platform authentication and invitation email. Rows carry no organization ID, so they are not exported or deleted per organization. Platform-level retention is a separate decision.",
                 organization_owned=False),
    DataCategory("messaging.conversations", "Conversations and messages", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "No conversation producer exists. Channel gateway is not built."),
    DataCategory("voice.call_records", "Voice call records", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "Voice (DFR1-027) is not built."),
    DataCategory("voice.transcripts", "Call transcripts and recordings", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "Voice transcription (DFR1-028) is not built."),
    DataCategory("ai.prompts_and_responses", "AI chat prompts and responses", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, False,
                 "No conversational or chat producer is persisted. Agent run outputs are exported under ai.execution_traces."),
    DataCategory("ai.embeddings", "Knowledge chunks (document text and index metadata)", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Chunk text and metadata are exported. Embedding vectors are derived numbers and are not exported. Chunks are deleted on request."),
    DataCategory("ai.usage", "AI usage ledger", Sensitivity.STANDARD, RetentionTreatment.MANDATORY_RECORD, True,
                 "Usage ledger (DFR1-017). Retained as a financial record. Cost entries are exported as metering only."),
    DataCategory("ai.execution_traces", "AI agent run records", Sensitivity.SENSITIVE_CONTENT, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Agent run inputs, outputs and step traces (DFR1-019). Agent definitions and prompts are internal configuration and are never exported."),
    DataCategory("crm.lead_intelligence", "Lead priority scores and corrections", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Scores are kept. Factors and human correction reasons are cleared on deletion."),
    DataCategory("crm.lead_intake", "Lead intake submissions", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Raw and normalized submitted data. The payload fingerprint and the decision are kept as evidence."),
    DataCategory("crm.lead_qualification", "Lead qualification findings", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Findings and human review notes."),
    DataCategory("automation.workflow_runs", "Workflow run records", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Run inputs, outputs and step traces. Definitions and versions are configuration and are not exported."),
    DataCategory("automation.human_tasks", "Human task records", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Task titles, instructions, decision comments and event history."),
    DataCategory("automation.rule_runs", "Automation rule run records", Sensitivity.PERSONAL, RetentionTreatment.ORGANIZATION_CONFIGURABLE, True,
                 "Action results and error messages."),
    DataCategory("security.credentials", "Provider credentials and secret references", Sensitivity.SECRET_REFERENCE, RetentionTreatment.NEVER_DELETE_BY_CUSTOMER, False,
                 "Secrets are never exported. Provider connection status is not part of any export yet (ADR-0032)."),
)

CATEGORY_BY_KEY: dict[str, DataCategory] = {category.key: category for category in CATEGORIES}


def is_customer_deletable(category: DataCategory) -> bool:
    """A category can be removed on request only when its treatment allows it."""
    return category.retention is RetentionTreatment.ORGANIZATION_CONFIGURABLE
