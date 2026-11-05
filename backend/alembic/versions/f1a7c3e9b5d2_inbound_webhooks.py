"""Inbound webhook endpoints, delivery records and their permission (DFR1-012).

Additive. Creates ``inbound_webhook_endpoints`` (server-side trust configuration with an encrypted signing secret) and
``inbound_webhook_deliveries`` (one row per verified or refused delivery). The partial unique index allows one accepted delivery per
endpoint and provider event, which makes duplicate deliveries safe under concurrency. Registers ``webhook_endpoints.manage`` and grants
it to the system Owner role only. Downgrade refuses while rows exist, because they record what was received and accepted.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a7c3e9b5d2"
down_revision: str | Sequence[str] | None = "e5a7c9d1f3b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (
        "webhook_endpoints.manage",
        "Create, rotate and disable inbound webhook endpoints and their signing secrets.",
    ),
)


def upgrade() -> None:
    op.create_table(
        "inbound_webhook_endpoints",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("verifier_key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "provider_connection_id",
            sa.Uuid(),
            sa.ForeignKey("provider_connections.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("secret_version", sa.Integer(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("secret_key_id", sa.String(length=64), nullable=True),
        sa.Column("secret_algorithm", sa.String(length=40), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "disabled_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "id", "organization_id", name="uq_inbound_webhook_endpoints_id_organization"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_inbound_webhook_endpoints_status",
        ),
        sa.CheckConstraint(
            "secret_version >= 1", name="ck_inbound_webhook_endpoints_version_positive"
        ),
        sa.CheckConstraint(
            "(status = 'active' AND secret_ciphertext IS NOT NULL AND secret_key_id IS NOT NULL"
            " AND secret_algorithm IS NOT NULL) OR (status = 'disabled' AND secret_ciphertext IS NULL)",
            name="ck_inbound_webhook_endpoints_secret_state",
        ),
    )
    op.create_index(
        "ix_inbound_webhook_endpoints_org",
        "inbound_webhook_endpoints",
        ["organization_id"],
    )

    op.create_table(
        "inbound_webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("timestamp_header", sa.String(length=20), nullable=True),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("body_bytes", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=True),
        sa.Column("outbox_event_id", sa.Uuid(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_id", "organization_id"],
            [
                "inbound_webhook_endpoints.id",
                "inbound_webhook_endpoints.organization_id",
            ],
            name="fk_inbound_webhook_deliveries_endpoint_tenant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'conflict', 'rejected', 'failed')",
            name="ck_inbound_webhook_deliveries_outcome",
        ),
        sa.CheckConstraint(
            "body_bytes >= 0", name="ck_inbound_webhook_deliveries_body_bytes"
        ),
    )
    op.create_index(
        "uq_inbound_webhook_deliveries_accepted_event",
        "inbound_webhook_deliveries",
        ["endpoint_id", "provider_event_id"],
        unique=True,
        postgresql_where=sa.text("outcome = 'accepted'"),
    )
    op.create_index(
        "ix_inbound_webhook_deliveries_org_received",
        "inbound_webhook_deliveries",
        ["organization_id", "received_at"],
    )

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
    connection.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id, created_at)
            SELECT gen_random_uuid(), r.id, p.id, now()
            FROM roles r
            JOIN permissions p ON p.key IN :keys
            WHERE r.name = 'DealFlow Owner' AND r.is_system = true
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id
              )
            """
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM inbound_webhook_endpoints) + (SELECT COUNT(*) FROM inbound_webhook_deliveries)"
        )
    ).scalar_one()
    if rows:
        raise RuntimeError(
            "Inbound webhook rows exist; downgrade would remove what was received and accepted."
        )
    op.drop_index(
        "ix_inbound_webhook_deliveries_org_received",
        table_name="inbound_webhook_deliveries",
    )
    op.drop_index(
        "uq_inbound_webhook_deliveries_accepted_event",
        table_name="inbound_webhook_deliveries",
    )
    op.drop_table("inbound_webhook_deliveries")
    op.drop_index(
        "ix_inbound_webhook_endpoints_org", table_name="inbound_webhook_endpoints"
    )
    op.drop_table("inbound_webhook_endpoints")
    connection.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE key IN :keys)"
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": [key for key, _ in NEW_PERMISSIONS]},
    )
