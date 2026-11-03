"""Provider connections and verification history (E06 WS4, ADR-0032).

Additive. A connection references an existing encrypted credential and holds no secret. Attempt
rows hold outcomes and reason codes only. The downgrade drops both tables and does not touch
``provider_credentials``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d8f1a9e2b7"
down_revision: str | Sequence[str] | None = "a1f7c3e9d2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_reason_code", sa.String(length=64), nullable=True),
        sa.Column("verified_credential_version", sa.Integer(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_verification_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('unverified', 'verifying', 'connected', 'degraded', 'failed', 'disconnected')",
            name="ck_provider_connections_status",
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="ck_provider_connections_failures_non_negative"
        ),
        sa.CheckConstraint("version >= 1", name="ck_provider_connections_version_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_provider_connections_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="fk_provider_connections_credential_id_provider_credentials",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_provider_connections_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_connections"),
    )
    op.create_index(
        "uq_provider_connections_live_provider",
        "provider_connections",
        ["organization_id", "provider_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'disconnected'"),
    )
    op.create_index(
        "uq_provider_connections_live_credential",
        "provider_connections",
        ["credential_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'disconnected'"),
    )
    op.create_index(
        "ix_provider_connections_due",
        "provider_connections",
        ["status", "next_verification_at"],
        unique=False,
    )

    op.create_table(
        "provider_verification_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=40), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("adapter_version", sa.String(length=40), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'transient_failure', 'permanent_failure', 'timed_out', 'not_verified')",
            name="ck_provider_verification_attempts_outcome",
        ),
        sa.CheckConstraint(
            "trigger IN ('created', 'rotated', 'manual', 'scheduled')",
            name="ck_provider_verification_attempts_trigger",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["provider_connections.id"],
            name="fk_provider_attempts_connection_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_provider_attempts_organization_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_verification_attempts"),
    )
    op.create_index(
        "ix_provider_verification_attempts_connection",
        "provider_verification_attempts",
        ["connection_id", "attempted_at"],
        unique=False,
    )
    op.create_index(
        "ix_provider_verification_attempts_organization",
        "provider_verification_attempts",
        ["organization_id", "attempted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_verification_attempts_organization",
        table_name="provider_verification_attempts",
    )
    op.drop_index(
        "ix_provider_verification_attempts_connection",
        table_name="provider_verification_attempts",
    )
    op.drop_table("provider_verification_attempts")
    op.drop_index("ix_provider_connections_due", table_name="provider_connections")
    op.drop_index("uq_provider_connections_live_credential", table_name="provider_connections")
    op.drop_index("uq_provider_connections_live_provider", table_name="provider_connections")
    op.drop_table("provider_connections")
