"""Lead intake submissions and lead qualification results (DFR1-021).

Additive. Creates ``lead_intake_submissions`` (raw and normalized intake, validation problems, identity candidates, the outcome and
the human decision) and ``lead_qualification_results`` (one per agent execution, with findings, review fields and provenance).
No permission is added. Downgrade refuses while rows exist, because they are the only record of what was received and decided.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e9d1f2b4"
down_revision: str | Sequence[str] | None = "f3b9d2c7a1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lead_intake_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_channel", sa.String(length=20), nullable=False),
        sa.Column("external_reference", sa.String(length=120), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=True),
        sa.Column("validation_problems", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("match_outcome", sa.String(length=30), nullable=True),
        sa.Column("candidate_contact_ids", sa.JSON(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("submitted_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "external_reference", name="uq_lead_intake_submissions_reference"),
        sa.CheckConstraint("status IN ('invalid', 'received', 'needs_review', 'processed', 'rejected')",
                           name="ck_lead_intake_submissions_status"),
        sa.CheckConstraint("source_channel IN ('manual', 'form', 'api')", name="ck_lead_intake_submissions_channel"),
    )
    op.create_index("ix_lead_intake_submissions_org_status", "lead_intake_submissions", ["organization_id", "status"])

    op.create_table(
        "lead_qualification_results",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), sa.ForeignKey("agent_executions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("score_id", sa.Uuid(), sa.ForeignKey("lead_priority_scores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("lead_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("review_reason", sa.String(length=500), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_lead_qualification_results_lead_org",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("execution_id", name="uq_lead_qualification_results_execution"),
        sa.CheckConstraint("review_status IN ('pending', 'accepted', 'overridden')",
                           name="ck_lead_qualification_results_review"),
    )
    op.create_index("ix_lead_qualification_results_org_lead", "lead_qualification_results",
                    ["organization_id", "lead_id", "created_at"])


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT (SELECT COUNT(*) FROM lead_intake_submissions) + (SELECT COUNT(*) FROM lead_qualification_results)"
    )).scalar_one()
    if rows:
        raise RuntimeError("Lead intake or qualification rows exist; downgrade would remove them.")
    op.drop_index("ix_lead_qualification_results_org_lead", table_name="lead_qualification_results")
    op.drop_table("lead_qualification_results")
    op.drop_index("ix_lead_intake_submissions_org_status", table_name="lead_intake_submissions")
    op.drop_table("lead_intake_submissions")
