"""Explainable lead priority results and human corrections (DFR1-020).

Additive. Creates ``lead_priority_scores`` (written once per computation, with the rule-set version, timestamp, factors and a hash
of the facts read) and ``lead_priority_corrections`` (human judgements recorded against one score for later evaluation). No
permission is added: the existing leads.read and leads.update permissions apply. Downgrade refuses while rows exist, because they
are the only record of computed priorities and of corrections.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3b9d2c7a1e4"
down_revision: str | Sequence[str] | None = "e2a8c4f1b9d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_priority_scores",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=60), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("band", sa.String(length=10), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("insufficient_data", sa.Boolean(), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("missing_factors", sa.JSON(), nullable=False),
        sa.Column("requirement_summary", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_lead_priority_scores_lead_org",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_lead_priority_scores_score"),
        sa.CheckConstraint("band IN ('high', 'medium', 'low')", name="ck_lead_priority_scores_band"),
    )
    op.create_index("ix_lead_priority_scores_org_lead_computed", "lead_priority_scores",
                    ["organization_id", "lead_id", "computed_at"])

    op.create_table(
        "lead_priority_corrections",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("score_id", sa.Uuid(), sa.ForeignKey("lead_priority_scores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("corrected_band", sa.String(length=10), nullable=True),
        sa.Column("corrected_score", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_lead_priority_corrections_idempotency"),
        sa.CheckConstraint("corrected_band IS NULL OR corrected_band IN ('high', 'medium', 'low')",
                           name="ck_lead_priority_corrections_band"),
        sa.CheckConstraint("corrected_score IS NULL OR (corrected_score >= 0 AND corrected_score <= 100)",
                           name="ck_lead_priority_corrections_score"),
    )
    op.create_index("ix_lead_priority_corrections_score", "lead_priority_corrections", ["score_id"])


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT (SELECT COUNT(*) FROM lead_priority_scores) + (SELECT COUNT(*) FROM lead_priority_corrections)"
    )).scalar_one()
    if rows:
        raise RuntimeError("Lead priority rows exist; downgrade would remove computed priorities and corrections.")
    op.drop_index("ix_lead_priority_corrections_score", table_name="lead_priority_corrections")
    op.drop_table("lead_priority_corrections")
    op.drop_index("ix_lead_priority_scores_org_lead_computed", table_name="lead_priority_scores")
    op.drop_table("lead_priority_scores")
