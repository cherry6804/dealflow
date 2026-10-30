"""Remove the automation grandfathering: existing organizations start disabled (DFR1-006).

Revision f3a7b9c1d2e4 enabled automation for every organization that existed when it ran,
without evidence of an opt-in. Decision: no independently verifiable explicit opt-in exists
in the database. Before E13 no organization-level automation switch existed, so no action
recorded an enablement. An active rule with a recorded last-updating user is not proof of
opt-in, and is not used.

This revision therefore:

1. Adds ``source`` to organization_capability_settings (the column records where a row came
   from; rows set by a person are ``manual``).
2. Removes only the blanket rows written by f3a7b9c1d2e4. They are identifiable: no actor,
   policy version 1, source ``manual``. Rows set by a person always record an actor.
3. Grants nothing. Every existing organization is disabled until an authorized organization
   administrator explicitly enables a capability under the policy.

Automation rules, their configurations, and their execution history are not changed. The
migration executes no rule and creates no notification.

Downgrade never re-enables anything. It drops the source column and leaves the remaining
rows as they are. It refuses to run when a person has changed a switch, so no administrator
change is discarded.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i7f2c9d4e1a8"
down_revision: str | Sequence[str] | None = "h5c9d1e3f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_capability_settings",
        sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
    )

    # Remove only the unevidenced blanket grants written by f3a7b9c1d2e4.
    op.execute(
        sa.text(
            """
            DELETE FROM organization_capability_settings
            WHERE capability_key = 'automation.master'
              AND updated_by_user_id IS NULL
              AND policy_version = 1
              AND source = 'manual'
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    changed_by_people = connection.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM organization_capability_settings
            WHERE updated_by_user_id IS NOT NULL
            """
        )
    ).scalar_one()
    if changed_by_people:
        raise RuntimeError(
            "Refusing to downgrade: people have changed capability switches since the upgrade. "
            "Export organization_capability_settings before downgrading."
        )
    # No rows are re-created: a downgrade must never silently re-enable a capability.
    op.drop_column("organization_capability_settings", "source")
