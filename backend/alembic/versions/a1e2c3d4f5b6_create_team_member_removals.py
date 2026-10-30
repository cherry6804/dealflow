"""Create the team member removal record.

Each removal of a Dealsflo team member is recorded with the actor, the organization,
the affected user, the reason and the seat outcome SIBVO confirmed. The membership
identifier has no foreign key, so the record survives the membership row.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1e2c3d4f5b6"
down_revision: str | Sequence[str] | None = "e5a7c1d9b2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_member_removals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("seat_outcome", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_team_member_removals_organization_id", "team_member_removals", ["organization_id"]
    )
    op.create_index(
        "ix_team_member_removals_membership_id", "team_member_removals", ["membership_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_team_member_removals_membership_id", table_name="team_member_removals")
    op.drop_index("ix_team_member_removals_organization_id", table_name="team_member_removals")
    op.drop_table("team_member_removals")
