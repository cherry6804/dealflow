"""Approvals, channel policy and contact do-not-disturb (DFR1-006, ADR-0029 gates 5 and 7).

Additive. Creates ``approval_requests``, ``channel_policies`` and ``contact_do_not_disturb``, and four permissions:
``governance.approvals.request`` and ``governance.approvals.decide``, ``governance.channels.read`` and
``governance.channels.manage``. DealFlow Owner receives all four. Admin receives the two read and request
permissions only. Downgrade refuses while rows exist, because they record approvals and configured restrictions.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "n5e8a1c4d7b9"
down_revision: str | Sequence[str] | None = ("b4d8f2a6c1e9", "l3c8e2f5a1b7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = (
    ("governance.approvals.request", "Request approval of an exact AI or automation payload."),
    ("governance.approvals.decide", "Approve or reject another member's approval request."),
    ("governance.channels.read", "View channel policy and contact do-not-disturb settings."),
    ("governance.channels.manage", "Configure channel policy and contact do-not-disturb."),
)
OWNER_PERMISSIONS = tuple(key for key, _ in NEW_PERMISSIONS)
ADMIN_PERMISSIONS = ("governance.approvals.request", "governance.channels.read")


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("capability_key", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "requested_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')", name="ck_approval_requests_status"
        ),
        sa.CheckConstraint("expires_at > requested_at", name="ck_approval_requests_expiry_after_request"),
    )
    op.create_index("ix_approval_requests_organization_id", "approval_requests", ["organization_id"])
    op.create_index("ix_approval_requests_org_status", "approval_requests", ["organization_id", "status"])

    op.create_table(
        "channel_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("messaging_days", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("messaging_start", sa.Time(), nullable=True),
        sa.Column("messaging_end", sa.Time(), nullable=True),
        sa.Column("quiet_start", sa.Time(), nullable=True),
        sa.Column("quiet_end", sa.Time(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "channel", name="uq_channel_policies_org_channel"),
        sa.CheckConstraint(
            "channel IN ('whatsapp', 'email', 'sms', 'voice')", name="ck_channel_policies_channel"
        ),
        sa.CheckConstraint("messaging_days BETWEEN 0 AND 127", name="ck_channel_policies_days"),
        sa.CheckConstraint(
            "(messaging_start IS NULL) = (messaging_end IS NULL)", name="ck_channel_policies_window_pair"
        ),
        sa.CheckConstraint("(quiet_start IS NULL) = (quiet_end IS NULL)", name="ck_channel_policies_quiet_pair"),
    )
    op.create_index("ix_channel_policies_org", "channel_policies", ["organization_id"])

    op.create_table(
        "contact_do_not_disturb",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("set_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "contact_id", name="uq_contact_dnd_org_contact"),
    )
    op.create_index("ix_contact_dnd_org", "contact_do_not_disturb", ["organization_id"])

    connection = op.get_bind()
    for key, description in NEW_PERMISSIONS:
        connection.execute(
            sa.text(
                """
                INSERT INTO permissions (id, key, description, is_active, created_at, updated_at)
                SELECT gen_random_uuid(), CAST(:key AS VARCHAR), CAST(:description AS VARCHAR), true, now(), now()
                WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE key = CAST(:key AS VARCHAR))
                """
            ),
            {"key": key, "description": description},
        )
    for role_name, keys in (("DealFlow Owner", OWNER_PERMISSIONS), ("Admin", ADMIN_PERMISSIONS)):
        connection.execute(
            sa.text(
                """
                INSERT INTO role_permissions (id, role_id, permission_id, created_at)
                SELECT gen_random_uuid(), r.id, p.id, now()
                FROM roles r
                JOIN permissions p ON p.key IN :keys
                WHERE r.name = :role_name AND r.is_system = true
                  AND NOT EXISTS (
                      SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
                  )
                """
            ).bindparams(sa.bindparam("keys", expanding=True)),
            {"keys": list(keys), "role_name": role_name},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("approval_requests", "channel_policies", "contact_do_not_disturb"):
        count = connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(
                f"Refusing to downgrade: {table} has rows. They record approvals or configured restrictions."
            )
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions WHERE permission_id IN (
                SELECT id FROM permissions WHERE key IN :keys
            )
            """
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(OWNER_PERMISSIONS)},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(OWNER_PERMISSIONS)},
    )
    op.drop_index("ix_contact_dnd_org", table_name="contact_do_not_disturb")
    op.drop_table("contact_do_not_disturb")
    op.drop_index("ix_channel_policies_org", table_name="channel_policies")
    op.drop_table("channel_policies")
    op.drop_index("ix_approval_requests_org_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_organization_id", table_name="approval_requests")
    op.drop_table("approval_requests")
