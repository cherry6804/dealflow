"""Property matching evaluation and next-best-action recommendations (DFR1-022).

Additive. Adds ``customer_requirements.transaction_type`` (NULL means not recorded), versioning columns on matching runs and
ranking columns on run results (NULL on runs made before this release), and ``next_best_action_recommendations``. No permission is
added. Downgrade refuses while recommendations exist, because they record what was recommended and the decisions made on them.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8d4f0a2c6e1"
down_revision: str | Sequence[str] | None = "a7c3e9d1f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customer_requirements", sa.Column("transaction_type", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        "ck_customer_requirements_transaction_type",
        "customer_requirements",
        "transaction_type IS NULL OR transaction_type IN ('SALE', 'RENT', 'LEASE')",
    )
    op.add_column("requirement_match_runs", sa.Column("ruleset_version", sa.String(length=60), nullable=True))
    op.add_column("requirement_match_runs", sa.Column("input_hash", sa.String(length=64), nullable=True))
    op.add_column("requirement_match_run_results", sa.Column("rank", sa.Integer(), nullable=True))
    op.add_column("requirement_match_run_results", sa.Column("eligibility", sa.String(length=30), nullable=True))
    op.add_column("requirement_match_run_results", sa.Column("ranking_basis", sa.JSON(), nullable=True))

    op.create_table(
        "next_best_action_recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_requirement_id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("subject_key", sa.String(length=120), nullable=False),
        sa.Column("basis", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("subject_property_id", sa.Uuid(), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=60), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            ["customer_requirements.id", "customer_requirements.organization_id"],
            name="fk_next_best_action_requirement_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_run_id", "organization_id"],
            ["requirement_match_runs.id", "requirement_match_runs.organization_id"],
            name="fk_next_best_action_run_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("match_run_id", "category", "subject_key", name="uq_next_best_action_run_category_subject"),
        sa.CheckConstraint(
            "basis IN ('verified_fact', 'deterministic_match', 'missing_information', 'ai_suggestion')",
            name="ck_next_best_action_basis",
        ),
        sa.CheckConstraint("status IN ('open', 'accepted', 'dismissed', 'done')", name="ck_next_best_action_status"),
    )
    op.create_index("ix_next_best_action_org_requirement", "next_best_action_recommendations",
                    ["organization_id", "customer_requirement_id"])


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT COUNT(*) FROM next_best_action_recommendations")).scalar_one()
    if rows:
        raise RuntimeError("Next-best-action recommendations exist; downgrade would remove them and their decisions.")
    op.drop_index("ix_next_best_action_org_requirement", table_name="next_best_action_recommendations")
    op.drop_table("next_best_action_recommendations")
    op.drop_column("requirement_match_run_results", "ranking_basis")
    op.drop_column("requirement_match_run_results", "eligibility")
    op.drop_column("requirement_match_run_results", "rank")
    op.drop_column("requirement_match_runs", "input_hash")
    op.drop_column("requirement_match_runs", "ruleset_version")
    op.drop_constraint("ck_customer_requirements_transaction_type", "customer_requirements", type_="check")
    op.drop_column("customer_requirements", "transaction_type")
