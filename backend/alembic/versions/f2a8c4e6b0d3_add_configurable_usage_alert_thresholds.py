"""Add configurable AI usage alert thresholds (WS6 WP2).

Adds:

- ``organization_usage_alert_settings``: one optional row per organization. A missing row means the
  defaults 70, 85 and 100, so no existing organization is changed by this migration.
- ``organization_usage_budgets.alerted_thresholds``: the configured thresholds already covered by a
  delivered alert for each budget period. It is backfilled from ``last_alert_percent``. Old code only
  ever stored 70, 85 or 100 there, so the backfill is exact for those values.

No budget amount, usage row, reservation or delivered alert is changed or deleted. ``last_alert_percent``
is kept and still holds the highest delivered threshold, so WP1 readers see the same values.

Downgrade drops the settings table and the new column. Organizations that had configured thresholds lose
their settings, and the defaults apply again. Delivered alerts stay recorded through
``last_alert_percent``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a8c4e6b0d3"
down_revision: str | Sequence[str] | None = "e6b1d7a4c9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_THRESHOLDS_SQL = "ARRAY[70, 85, 100]"


def upgrade() -> None:
    op.create_table(
        "organization_usage_alert_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("threshold_low", sa.SmallInteger(), nullable=False),
        sa.Column("threshold_mid", sa.SmallInteger(), nullable=False),
        sa.Column("threshold_high", sa.SmallInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", name="uq_organization_usage_alert_settings_org"),
        sa.CheckConstraint(
            "threshold_low >= 1 AND threshold_low < threshold_mid "
            "AND threshold_mid < threshold_high AND threshold_high = 100",
            name="ck_organization_usage_alert_settings_order",
        ),
    )

    op.add_column(
        "organization_usage_budgets",
        sa.Column(
            "alerted_thresholds",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    # Stored as a JSON list, matching the model. Only values 70, 85 and 100 can be recorded by the
    # WP1 code, so the backfill rule below reproduces them exactly.
    op.execute(
        sa.text(
            "UPDATE organization_usage_budgets "
            f"SET alerted_thresholds = COALESCE((SELECT json_agg(t ORDER BY t) "
            f"FROM (SELECT unnest({DEFAULT_THRESHOLDS_SQL}) AS t) AS defaults "
            "WHERE t <= last_alert_percent), '[]'::json) "
            "WHERE last_alert_percent > 0"
        )
    )


def downgrade() -> None:
    op.drop_column("organization_usage_budgets", "alerted_thresholds")
    op.drop_table("organization_usage_alert_settings")
