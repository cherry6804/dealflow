"""Add audit lifecycle columns and immutability for audit_events (WS6 WP3).

Adds three nullable columns to ``audit_events``:

- ``outcome``: requested, completed or denied. Null for rows written before WP3.
- ``causation_id``: the requested row a completed row follows from.
- ``idempotency_key``: at most one row per organization and key, enforced by a partial unique index.

Adds a PostgreSQL trigger that rejects any ``UPDATE`` of an audit row. The one permitted change is the
foreign-key action ``ON DELETE SET NULL`` on ``user_id`` or ``organization_id``, which runs when the
referenced row is deleted. Without that exception, deleting a user would fail. Application code never
updates audit rows, so the trigger changes no current behaviour.

No existing row is changed or removed. Downgrade drops the trigger, its function, the index and the
columns. Rows keep their content, and any lifecycle information stored only in the new columns is lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d8f2a6c1e9"
down_revision: str | Sequence[str] | None = "f2a8c4e6b0d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION reject_audit_event_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.occurred_at, NEW.event_type, NEW.action, NEW.decision, NEW.outcome,
        NEW.permission_key, NEW.resource_type, NEW.resource_id, NEW.correlation_id,
        NEW.causation_id, NEW.idempotency_key, NEW.event_metadata)
       IS DISTINCT FROM
       (OLD.id, OLD.occurred_at, OLD.event_type, OLD.action, OLD.decision, OLD.outcome,
        OLD.permission_key, OLD.resource_type, OLD.resource_id, OLD.correlation_id,
        OLD.causation_id, OLD.idempotency_key, OLD.event_metadata) THEN
        RAISE EXCEPTION 'audit_events rows are immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    -- Only the foreign-key SET NULL that follows a deleted user or organization may change these.
    IF NEW.user_id IS DISTINCT FROM OLD.user_id AND NEW.user_id IS NOT NULL THEN
        RAISE EXCEPTION 'audit_events.user_id is immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id AND NEW.organization_id IS NOT NULL THEN
        RAISE EXCEPTION 'audit_events.organization_id is immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("outcome", sa.String(length=20), nullable=True))
    op.add_column("audit_events", sa.Column("causation_id", sa.String(length=200), nullable=True))
    op.add_column("audit_events", sa.Column("idempotency_key", sa.String(length=200), nullable=True))
    op.create_index(
        "uq_audit_events_org_idempotency_key",
        "audit_events",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.execute(TRIGGER_FUNCTION_SQL)
    op.execute(
        "CREATE TRIGGER audit_events_immutable BEFORE UPDATE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_change()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_event_change()")
    op.drop_index("uq_audit_events_org_idempotency_key", table_name="audit_events")
    op.drop_column("audit_events", "idempotency_key")
    op.drop_column("audit_events", "causation_id")
    op.drop_column("audit_events", "outcome")
