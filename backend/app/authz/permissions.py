"""Canonical permission catalogue and organization role permission sets."""

from __future__ import annotations


PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    ("contacts.read", "View contacts."),
    ("contacts.create", "Create contacts."),
    ("contacts.update", "Update contacts."),
    ("contacts.delete", "Delete contacts."),
    ("leads.read", "View leads."),
    ("leads.create", "Create leads."),
    ("leads.update", "Update leads."),
    ("leads.delete", "Delete leads."),
    ("properties.read", "View properties."),
    ("properties.create", "Create properties."),
    ("properties.update", "Update properties."),
    ("properties.delete", "Delete properties."),
    ("requirements.read", "View requirements."),
    ("requirements.create", "Create requirements."),
    ("requirements.update", "Update requirements."),
    ("requirements.delete", "Delete requirements."),
    ("imports.read", "View import jobs."),
    ("imports.create", "Create import jobs."),
    ("deals.read", "View deals."),
    ("deals.create", "Create deals."),
    ("deals.update", "Update deals."),
    ("deals.delete", "Delete deals."),
    ("deals.close", "Close deals."),
    ("deal_negotiations.read", "View deal negotiations."),
    ("deal_negotiations.create", "Create deal negotiations."),
    ("deal_negotiations.update", "Update deal negotiations."),
    ("payment_milestones.read", "View payment milestones."),
    ("payment_milestones.create", "Create payment milestones."),
    ("payment_milestones.update", "Update payment milestones."),
    ("commission.read", "View commissions."),
    ("commission.create", "Create commissions."),
    ("commission.update", "Update commissions."),
    ("referrals.read", "View referrals."),
    ("referrals.create", "Create referrals."),
    ("referrals.update", "Update referrals."),
    ("documents.read", "View documents."),
    ("documents.upload", "Upload documents."),
    ("documents.download", "Download documents."),
    ("automation.read", "View automation settings."),
    ("automation.create", "Create automations."),
    ("automation.update", "Update automations."),
    ("billing.audit.read", "View billing audit records."),
    ("notifications.preferences.read", "View notification preferences."),
    ("notifications.preferences.update", "Update notification preferences."),
    ("organization.members.read", "View organization members."),
    ("organization.members.manage", "Manage organization memberships."),
    ("organization.invites.manage", "Create and manage invitations."),
    ("organization.roles.manage", "Create and manage organization roles."),
    ("governance.capabilities.read", "View AI and automation capability settings."),
    ("governance.capabilities.manage", "Change AI and automation capability settings."),
    ("governance.usage.read", "View AI usage, budgets and provider cost."),
    ("governance.budgets.manage", "Set organization AI usage budgets."),
    ("governance.privacy.read", "View retention policies, legal holds and privacy requests."),
    ("governance.privacy.manage", "Change retention, legal holds and privacy requests."),
    ("provider_credentials.read", "View provider credential metadata."),
    ("provider_credentials.manage", "Create, rotate and revoke provider credentials."),
)

PERMISSION_DESCRIPTIONS: dict[str, str] = dict(PERMISSION_CATALOG)

OWNER_ONLY_PERMISSION_KEYS = frozenset(
    {
        "organization.roles.manage",
        "billing.audit.read",
        "governance.capabilities.manage",
        "governance.budgets.manage",
        "governance.privacy.manage",
        "provider_credentials.manage",
    }
)

# The system Owner role. Owner-only permission keys are granted only through this role.
OWNER_ROLE_NAME = "DealFlow Owner"

OWNER_ROLE_PERMISSION_KEYS = tuple(
    key for key, _description in PERMISSION_CATALOG
)