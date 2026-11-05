"""Workflow executions and their step records (DFR1-024).

An execution is pinned to one immutable workflow version when it starts, so a later publish, pause or rollback never changes it. Each
execution has a state, a step pointer and a record per step. The step record is written before the next step runs, so a restart
resumes at the first step that has no finished record. Idempotency keys are unique per organization, so a repeated request or a
duplicate event creates no second execution.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_executions_idempotency"),
        UniqueConstraint("id", "organization_id", name="uq_workflow_executions_id_organization"),
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'waiting_timer', 'succeeded', 'failed', "
            "'cancelled', 'stopped', 'timed_out', 'dead_letter')",
            name="ck_workflow_executions_status",
        ),
        CheckConstraint("trigger_type IN ('manual', 'event')", name="ck_workflow_executions_trigger"),
        Index("ix_workflow_executions_org_workflow_status", "organization_id", "workflow_id", "status"),
        Index("ix_workflow_executions_org_created", "organization_id", "created_at"),
    )

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_WAITING_APPROVAL = "waiting_approval"
    STATUS_WAITING_TIMER = "waiting_timer"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_STOPPED = "stopped"
    STATUS_TIMED_OUT = "timed_out"
    STATUS_DEAD_LETTER = "dead_letter"

    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_WAITING_APPROVAL, STATUS_WAITING_TIMER)
    TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELLED, STATUS_STOPPED, STATUS_TIMED_OUT,
                         STATUS_DEAD_LETTER)
    RETRYABLE_STATUSES = (STATUS_FAILED, STATUS_DEAD_LETTER, STATUS_TIMED_OUT, STATUS_STOPPED)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    # Tenant ownership is enforced by the runtime, which reads the definition by organization before it creates a run.
    workflow_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_versions.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(10), nullable=False)
    trigger_event: Mapped[str | None] = mapped_column(String(60), nullable=True)
    event_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    retry_of_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    run_as_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    initiated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    next_step_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    steps_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkflowExecutionStep(Base):
    __tablename__ = "workflow_execution_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_id", name="uq_workflow_execution_steps_step"),
        ForeignKeyConstraint(
            ["execution_id", "organization_id"],
            ["workflow_executions.id", "workflow_executions.organization_id"],
            name="fk_workflow_execution_steps_execution_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'waiting_approval', 'waiting_timer', 'cancelled')",
            name="ck_workflow_execution_steps_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    step_id: Mapped[str] = mapped_column(String(40), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
