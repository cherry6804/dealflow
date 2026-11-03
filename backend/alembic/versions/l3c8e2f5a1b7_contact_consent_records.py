"""Append-only consent records and their permissions (DFR1-006, ADR-0029 gate 7).

Additive. Creates ``contact_consent_records`` and two permissions. ``governance.consent.read`` is granted
to the Admin and DealFlow Owner system roles, and ``governance.consent.manage`` to DealFlow Owner only.
Downgrade removes the table and the two permission rows. Consent history is the audit trail, so the
downgrade refuses to drop the table while any consent record exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l3c8e2f5a1b7"
down_revision: str | Sequence[str] | None = "k2b7d4e9a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSENT_PERMISSIONS = (
    ("governance.consent.read", "View contact consent records and their history."),
    ("governance.consent.manage", "Record consent grants, revocations and expiries."),
)


def upgrade() -> None:
    op.create_table(
        "contact_consent_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="contact"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recorded_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "channel IN ('whatsapp', 'email', 'sms', 'voice')",
            name="ck_contact_consent_records_channel",
        ),
        sa.CheckConstraint(
            "purpose IN ('customer_service', 'marketing', 'automated_follow_up', 'voice_outreach')",
            name="ck_contact_consent_records_purpose",
        ),
        sa.CheckConstraint("status IN ('granted', 'revoked')", name="ck_contact_consent_records_status"),
        sa.CheckConstraint(
            "status <> 'granted' OR expires_at IS NULL OR expires_at > recorded_at",
            name="ck_contact_consent_records_expiry_after_grant",
        ),
    )
    op.create_index("ix_contact_consent_records_organization_id", "contact_consent_records", ["organization_id"])
    op.create_index(
        "ix_contact_consent_records_lookup",
        "contact_consent_records",
        ["organization_id", "contact_id", "channel", "purpose", "recorded_at"],
    )

    connection = op.get_bind()
    for key, description in CONSENT_PERMISSIONS:
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
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.key IN ('governance.consent.read', 'governance.consent.manage')
            WHERE r.name = 'DealFlow Owner' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.key = 'governance.consent.read'
            WHERE r.name = 'Admin' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    records = connection.execute(sa.text("SELECT COUNT(*) FROM contact_consent_records")).scalar_one()
    if records:
        raise RuntimeError(
            "Refusing to downgrade: consent records exist. They are the consent audit trail and are not dropped."
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions WHERE permission_id IN (
                SELECT id FROM permissions WHERE key IN ('governance.consent.read', 'governance.consent.manage')
            )
            """
        )
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN ('governance.consent.read', 'governance.consent.manage')")
    )
    op.drop_index("ix_contact_consent_records_lookup", table_name="contact_consent_records")
    op.drop_index("ix_contact_consent_records_organization_id", table_name="contact_consent_records")
    op.drop_table("contact_consent_records")
