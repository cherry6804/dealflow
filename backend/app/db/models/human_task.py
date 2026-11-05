"""Human tasks and their immutable event history (DFR1-025).

A human task asks one member, or any member who holds a named permission, to decide something a workflow is waiting on. An approval
task is bound to one exact payload through the governance approval record it owns (``approval_requests``), so the decision covers
exactly that payload. The task holds the current state; every change to it, including creation, assignment, comments and the decision,
is appended to ``human_task_events``. That table is append-only: the database refuses UPDATE and DELETE, as it does for workflow
versions, so the history cannot be rewritten.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TASK_STATUSES = ("pending", "approved", "rejected", "cancelled", "expired")
TASK_EVENT_TYPES = ("created", "assigned", "reassigned", "comment", "approved", "rejected", "cancelled", "expired")


class HumanTask(Base):
    __tablename__ = "human_tasks"
    __table_args__ = (
        UniqueConstraint("organization_id", "workflow_execution_id", "workflow_step_id",
                         name="uq_human_tasks_execution_step"),
        UniqueConstraint("approval_request_id", name="uq_human_tasks_approval_request"),
        UniqueConstraint("id", "organization_id", name="uq_human_tasks_id_organization"),
        CheckConstraint("kind IN ('approval')", name="ck_human_tasks_kind"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')",
            name="ck_human_tasks_status",
        ),
        Index("ix_human_tasks_org_status_due", "organization_id", "status", "due_at"),
    )

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="approval")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_permission: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="RESTRICT"), nullable=True
    )
    workflow_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    workflow_step_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HumanTaskEvent(Base):
    __tablename__ = "human_task_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'assigned', 'reassigned', 'comment', 'approved', 'rejected', 'cancelled', 'expired')",
            name="ck_human_task_events_type",
        ),
        Index("ix_human_task_events_task", "organization_id", "task_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("human_tasks.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    to_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


_IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION human_task_events_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'human task events are immutable';
END;
$$ LANGUAGE plpgsql
"""
_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_human_task_events_immutable
BEFORE UPDATE OR DELETE ON human_task_events
FOR EACH ROW EXECUTE FUNCTION human_task_events_immutable()
"""
# Only PostgreSQL supports this trigger. Other dialects (used by some unit tests) skip it.
for _statement in (
    _IMMUTABLE_FUNCTION,
    "DROP TRIGGER IF EXISTS trg_human_task_events_immutable ON human_task_events",
    _IMMUTABLE_TRIGGER,
):
    event.listen(HumanTaskEvent.__table__, "after_create", DDL(_statement).execute_if(dialect="postgresql"))
