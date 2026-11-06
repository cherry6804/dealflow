"""Table-level privacy inventory: every database table has exactly one disposition (DFR1-050).

The category register in ``data_classification.py`` describes what the privacy controls can act on. This module
answers a stricter question for every table in the database: where does it stand? A test fails when a table is
added without an entry, or when an entry names a table that no longer exists. Nothing is silently excluded.

Dispositions:
- ``exported``: read by an export under the named category. Export and deletion are still governed by the
  category register.
- ``not_covered``: neither exported nor deleted by any request. The reason names the open decision.
- ``sibvo_owned``: membership, subscription and identity link data owned by SIBVO. Dealsflo does not change it (D6).
- ``configuration``: definitions and settings, not customer data.
- ``governance_record``: audit, billing, privacy request and approval records kept as evidence.
- ``platform_record``: platform-wide records with no organization scope (users, organizations, outbox).
- ``never_exported``: credentials and secret references, which are never exported.

This is a proposal for review under decision D9. A disposition never authorizes deletion or anonymization.
"""

from __future__ import annotations

from dataclasses import dataclass

DISPOSITION_EXPORTED = "exported"
DISPOSITION_NOT_COVERED = "not_covered"
DISPOSITION_SIBVO_OWNED = "sibvo_owned"
DISPOSITION_CONFIGURATION = "configuration"
DISPOSITION_GOVERNANCE_RECORD = "governance_record"
DISPOSITION_PLATFORM_RECORD = "platform_record"
DISPOSITION_NEVER_EXPORTED = "never_exported"

DISPOSITIONS = (
    DISPOSITION_EXPORTED,
    DISPOSITION_NOT_COVERED,
    DISPOSITION_SIBVO_OWNED,
    DISPOSITION_CONFIGURATION,
    DISPOSITION_GOVERNANCE_RECORD,
    DISPOSITION_PLATFORM_RECORD,
    DISPOSITION_NEVER_EXPORTED,
)


@dataclass(frozen=True)
class TableEntry:
    disposition: str
    category: str | None = None
    reason: str = ""


def _exported(category: str) -> TableEntry:
    return TableEntry(DISPOSITION_EXPORTED, category)


def _not_covered(reason: str) -> TableEntry:
    return TableEntry(DISPOSITION_NOT_COVERED, reason=reason)


TABLE_INVENTORY: dict[str, TableEntry] = {
    # Customer and CRM data, exported under its category.
    "contacts": _exported("crm.contacts"),
    "leads": _exported("crm.leads"),
    "customer_profiles": _exported("crm.customer_profiles"),
    "customer_requirements": _exported("crm.requirements"),
    "customer_requirement_history": _exported("crm.requirements"),
    "customer_requirement_locations": _exported("crm.requirements"),
    "customer_requirement_property_preferences": _exported("crm.requirements"),
    "customer_requirement_possession_parking_preferences": _exported("crm.requirements"),
    "deals": _exported("crm.deals"),
    "deal_commissions": _exported("crm.deals"),
    "payment_milestones": _exported("crm.deals"),
    "deal_negotiations": _exported("crm.deals"),
    "deal_negotiation_history": _exported("crm.deals"),
    "deal_stage_history": _exported("crm.deals"),
    "follow_ups": _exported("crm.follow_ups"),
    "activities": _exported("crm.follow_ups"),
    "documents": _exported("documents.files"),
    "team_invitations": _exported("team.invitations"),
    "ai_usage_events": _exported("ai.usage"),
    "ai_provider_prices": TableEntry(DISPOSITION_CONFIGURATION, reason="Platform provider price versions. Configuration, not customer data."),
    "ai_provider_cost_entries": _exported("ai.usage"),
    # Platform email outbox: no organization column. Excluded from per-organization export (D5).
    "email_outbox_messages": TableEntry(
        DISPOSITION_NOT_COVERED,
        category="messaging.email_outbox",
        reason="Platform email outbox. No organization column. Excluded by decision D5.",
    ),
    # Customer or personal data with no export or deletion yet.
    "properties": _exported("crm.properties"),
    "referrals": _exported("crm.referrals"),
    "site_visits": _exported("crm.site_visits"),
    "requirement_match_runs": _exported("crm.requirement_matching"),
    "requirement_match_run_results": _exported("crm.requirement_matching"),
    "requirement_property_shortlists": _exported("crm.requirement_matching"),
    "requirement_shortlist_events": _exported("crm.requirement_matching"),
    "notifications": _exported("messaging.notifications"),
    "notification_preferences": _exported("messaging.notifications"),
    # The uploaded file is exported and removed under documents.files. The batch row is kept, because
    # imported contacts reference it. This is reported as partial, never as a full deletion.
    "import_batches": _not_covered("Partially covered. The uploaded file is exported and removed under documents.files. The file name, the error summary and any personal text are cleared. Only a minimal technical record is kept: identifiers, organization, source format, content type, file size, status, row counts and timestamps. The row stays because imported contacts reference it with ON DELETE RESTRICT (DFR1-050)."),
    "team_member_removals": _exported("team.invitations"),
    "automation_executions": _exported("automation.rule_runs"),
    "contact_consent_records": _exported("crm.contacts"),
    "contact_do_not_disturb": _exported("crm.contacts"),
    # Governance and privacy evidence.
    "audit_events": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Security and governance records. Never deleted by a request."),
    "billing_reconciliation_records": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Financial records. Export excluded by decision D3."),
    "billing_webhook_events": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Financial records. Export excluded by decision D3."),
    "approval_requests": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Approval evidence with actor identifiers."),
    "privacy_data_requests": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Privacy request evidence."),
    "privacy_legal_holds": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Legal hold evidence."),
    "privacy_retention_policies": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Retention configuration evidence."),
    # Configuration.
    "automation_rules": TableEntry(DISPOSITION_CONFIGURATION, reason="Rule definitions."),
    "organization_capability_settings": TableEntry(DISPOSITION_CONFIGURATION, reason="Switch settings and their change records."),
    "knowledge_chunks": _exported("ai.embeddings"),
    "agents": TableEntry(DISPOSITION_CONFIGURATION, reason="Agent definitions: name, description, instructions and the draft configuration. Internal configuration and prompts. Never exported."),
    "agent_versions": TableEntry(DISPOSITION_CONFIGURATION, reason="Immutable published agent configurations, instructions and validation snapshots. Internal configuration. Never exported."),
    "agent_executions": _exported("ai.execution_traces"),
    "agent_execution_steps": _exported("ai.execution_traces"),
    "lead_priority_scores": _exported("crm.lead_intelligence"),
    "lead_priority_corrections": _exported("crm.lead_intelligence"),
    "next_best_action_recommendations": _exported("crm.requirement_matching"),
    "workflow_definitions": TableEntry(DISPOSITION_CONFIGURATION, reason="Workflow definition: name, description, draft configuration and lifecycle status. Organization-owned configuration with no personal data."),
    "workflow_versions": TableEntry(DISPOSITION_CONFIGURATION, reason="Immutable published workflow versions and their configuration. Never updated or deleted."),
    "workflow_lifecycle_events": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Workflow lifecycle history: publish, pause, resume and rollback with the acting member and a reason. Governance evidence of configuration changes. Not exported to customers."),
    "workflow_executions": _exported("automation.workflow_runs"),
    "workflow_execution_steps": _exported("automation.workflow_runs"),
    "human_tasks": _exported("automation.human_tasks"),
    "human_task_events": _exported("automation.human_tasks"),
    "lead_intake_submissions": _exported("crm.lead_intake"),
    "lead_qualification_results": _exported("crm.lead_qualification"),
    "document_reviews": _exported("documents.files"),
    "ai_task_routes": TableEntry(DISPOSITION_CONFIGURATION, reason="Provider and model choice per AI task. Holds no credential."),
    "organization_usage_budgets": TableEntry(DISPOSITION_CONFIGURATION, reason="Budget configuration and aggregate quantities."),
    "channel_policies": TableEntry(DISPOSITION_CONFIGURATION, reason="Channel configuration."),
    "roles": TableEntry(DISPOSITION_CONFIGURATION, reason="Role definitions."),
    "role_permissions": TableEntry(DISPOSITION_CONFIGURATION, reason="Role definitions."),
    "permissions": TableEntry(DISPOSITION_CONFIGURATION, reason="Permission definitions."),
    "membership_roles": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Role assignment belongs to membership (D6)."),
    # SIBVO-owned identity, membership and subscription data (D6).
    "organization_memberships": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Membership is owned by SIBVO (D6)."),
    "subscriptions": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Subscription state is owned by SIBVO (D6)."),
    "plans": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Plan definitions are owned by SIBVO."),
    "plan_entitlements": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Plan entitlements are owned by SIBVO."),
    "sibvo_identity_links": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Identity link maintained from SIBVO."),
    "sibvo_organization_links": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Organization link maintained from SIBVO."),
    # Platform records with no organization scope.
    "users": TableEntry(DISPOSITION_PLATFORM_RECORD, reason="Account identity. Account deletion is a separate decision."),
    "organizations": TableEntry(DISPOSITION_PLATFORM_RECORD, reason="Tenant root record."),
    "outbox_events": TableEntry(DISPOSITION_PLATFORM_RECORD, reason="Internal delivery queue. Carries no personal values by design."),
    # Credentials and secret references: never exported.
    "auth_sessions": TableEntry(DISPOSITION_NEVER_EXPORTED, reason="Session credentials."),
    "auth_login_rate_limits": TableEntry(DISPOSITION_NEVER_EXPORTED, reason="Login throttling state."),
    "email_verification_tokens": TableEntry(DISPOSITION_NEVER_EXPORTED, reason="Single-use token material."),
    "password_reset_tokens": TableEntry(DISPOSITION_NEVER_EXPORTED, reason="Single-use token material."),
    "provider_connections": TableEntry(DISPOSITION_NEVER_EXPORTED, category="security.credentials", reason="Connection metadata that references encrypted credentials. Never exported."),
    "inbound_webhook_endpoints": TableEntry(DISPOSITION_NEVER_EXPORTED, category="security.credentials", reason="Inbound webhook endpoint configuration with an encrypted signing secret. Never exported; the secret is shown once at creation or rotation."),
    "inbound_webhook_deliveries": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Delivery evidence: outcome, reason code and hashes. Accepted deliveries keep a redacted envelope. Security evidence, not customer data. Not exported."),
    "provider_credentials": TableEntry(DISPOSITION_NEVER_EXPORTED, category="security.credentials", reason="Encrypted provider secret material. Never exported or returned."),
    "provider_verification_attempts": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Verification outcomes and reason codes only. Kept as evidence."),
    "organization_entitlement_snapshots": TableEntry(DISPOSITION_SIBVO_OWNED, reason="Entitlement snapshot received from SIBVO. Dealsflo does not change it (D6)."),
    "organization_usage_alert_settings": TableEntry(DISPOSITION_CONFIGURATION, reason="Configured alert thresholds."),
    "outbox_replay_records": TableEntry(DISPOSITION_GOVERNANCE_RECORD, reason="Operator replay evidence for outbox events."),
    "execution_rate_limit_windows": TableEntry(DISPOSITION_PLATFORM_RECORD, reason="Rate-limit counters keyed by an actor identifier. System operational state with no customer content."),
}
