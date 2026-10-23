
"""Canonical permission catalog for DealFlow authorization."""

PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    ("contacts.create", "Create contacts"),
    ("contacts.read", "View contacts"),
    ("contacts.update", "Update contacts"),
    ("leads.create", "Create leads"),
    ("leads.read", "View leads"),
    ("leads.update", "Update leads"),
    ("properties.create", "Create properties"),
    ("properties.read", "View properties"),
    ("properties.update", "Update properties"),
    ("requirements.create", "Create requirements"),
    ("requirements.read", "View requirements"),
    ("requirements.update", "Update requirements"),
    ("imports.upload", "Upload data imports"),
    ("deals.create", "Create deals"),
    ("deals.read", "View deals"),
    ("deals.update", "Update deals"),
    ("deal_negotiations.read", "View deal negotiations"),
    ("deal_negotiations.update", "Update deal negotiations"),
    ("payment_milestones.read", "View payment milestones"),
    ("payment_milestones.create", "Create payment milestones"),
    ("payment_milestones.update", "Update payment milestones"),
    ("commission.read", "View deal commissions"),
    ("commission.create", "Create deal commissions"),
    ("commission.update", "Update deal commissions"),
    ("referrals.read", "View referrals"),
    ("referrals.create", "Create referrals"),
    ("referrals.update", "Update referrals"),
    ("documents.read", "View documents"),
    ("documents.upload", "Upload documents"),
    ("documents.download", "Download documents"),
    ("documents.manage", "Manage documents"),
    ("automation.read", "View automation rules"),
    ("automation.create", "Create automation rules"),
    ("automation.update", "Update automation rules"),
    ("billing.audit.read", "View billing audit records"),
    ("notifications.preferences.read", "View notification preferences"),
    ("notifications.preferences.update", "Update notification preferences"),
)

OWNER_ROLE_PERMISSION_KEYS: tuple[str, ...] = tuple(
    key for key, _description in PERMISSION_CATALOG
)
