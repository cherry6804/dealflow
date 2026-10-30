"""Correct the automation default: grant only on reliable evidence of prior opt-in (DFR1-006).

Revision f3a7b9c1d2e4 enabled automation for every organization that existed when it ran.
That granted automation without evidence. This revision corrects it:

1. Adds ``source`` to organization_capability_settings. Rows are either ``manual`` (set by a
   person through the settings API) or ``migration_evidence_active_rule``.
2. Removes the blanket rows written by f3a7b9c1d2e4. They are identifiable: no actor,
   policy version 1, source ``manual``. Rows set by a person always record an actor.
3. Grants automation (master and deal-created rules) only to organizations that have a
   DEAL_CREATED automation rule with status ACTIVE and a recorded activating user. Activation
   is an explicit user action, so that is the only reliable prior opt-in in the database.
   Organizations without such a rule, including those with only draft or disabled rules,
   stay disabled.

Automation rule rows are not changed. Historical executions are not changed.

Downgrade restores the blanket state of f3a7b9c1d2e4 and drops the source column. It refuses
to run when a person has changed a capability switch, so that such changes are not lost
silently. Export those rows before downgrading.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i7f2c9d4e1a8"
down_revision: str | Sequence[str] | None = "h5c9d1e3f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVIDENCE_SOURCE = "migration_evidence_active_rule"
EVIDENCE_CAPABILITIES = ("automation.master", "automation.deal_created_rules")


def upgrade() -> None:
    op.add_column(
        "organization_capability_settings",
        sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
    )

    # 1. Remove the unevidenced blanket grants written by f3a7b9c1d2e4.
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

    # 2. Grant only where an active deal-created rule has a known activating user.
    for capability_key in EVIDENCE_CAPABILITIES:
        op.execute(
            sa.text(
                """
                INSERT INTO organization_capability_settings
                    (id, organization_id, capability_key, is_enabled, policy_version, source,
                     updated_by_user_id, created_at, updated_at)
                SELECT gen_random_uuid(), e.organization_id, CAST(:capability_key AS VARCHAR), true, 1,
                       CAST(:source AS VARCHAR), NULL, now(), now()
                FROM (
                    SELECT DISTINCT organization_id
                    FROM automation_rules
                    WHERE status = 'ACTIVE'
                      AND trigger_type = 'DEAL_CREATED'
                      AND updated_by_user_id IS NOT NULL
                ) AS e
                WHERE NOT EXISTS (
                    SELECT 1 FROM organization_capability_settings s
                    WHERE s.organization_id = e.organization_id
                      AND s.capability_key = CAST(:capability_key AS VARCHAR)
                )
                """
            ).bindparams(capability_key=capability_key, source=EVIDENCE_SOURCE)
        )


def downgrade() -> None:
    connection = op.get_bind()
    changed_by_people = connection.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM organization_capability_settings
            WHERE source = 'manual' AND updated_by_user_id IS NOT NULL
            """
        )
    ).scalar_one()
    if changed_by_people:
        raise RuntimeError(
            "Refusing to downgrade: people have changed capability switches since the upgrade. "
            "Export organization_capability_settings before downgrading."
        )

    op.execute(
        sa.text(
            "DELETE FROM organization_capability_settings WHERE source = 'migration_evidence_active_rule'"
        )
    )
    # Restore the state written by f3a7b9c1d2e4 for organizations that still have no master row.
    op.execute(
        sa.text(
            """
            INSERT INTO organization_capability_settings
                (id, organization_id, capability_key, is_enabled, policy_version, updated_by_user_id,
                 created_at, updated_at)
            SELECT gen_random_uuid(), o.id, 'automation.master', true, 1, NULL, now(), now()
            FROM organizations o
            WHERE NOT EXISTS (
                SELECT 1 FROM organization_capability_settings s
                WHERE s.organization_id = o.id AND s.capability_key = 'automation.master'
            )
            """
        )
    )
    op.drop_column("organization_capability_settings", "source")
