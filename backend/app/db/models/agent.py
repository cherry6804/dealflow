"""Agent definitions, immutable published versions, executions and execution steps (DFR1-019).

An agent has one mutable draft configuration and any number of published versions. A published version is never updated: it is
written once, and the agent points at one of them. Each execution is bound to the exact version it started with, so a later
publish, pause or rollback never changes an execution already running.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_agents_organization_name"),
        Index("ix_agents_organization_id", "organization_id"),
    )

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_PAUSED = "paused"
    STATUS_ARCHIVED = "archived"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_DRAFT,
                                        server_default=text("'draft'"))
    draft_configuration: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentVersion(Base):
    """One published version. It is written once, and the service never updates it."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_agent_versions_agent_number"),
        Index("ix_agent_versions_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    validation_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    published_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_agent_executions_org_idempotency"),
        Index("ix_agent_executions_agent_status", "agent_id", "status"),
        Index("ix_agent_executions_organization_created", "organization_id", "created_at"),
    )

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_WAITING_APPROVAL = "waiting_approval"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_TIMED_OUT = "timed_out"
    STATUS_CANCELLED = "cancelled"
    STATUS_STOPPED = "stopped"
    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_WAITING_APPROVAL)
    TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_FAILED, STATUS_TIMED_OUT, STATUS_CANCELLED, STATUS_STOPPED)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False)
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=STATUS_QUEUED)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_values: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    workflow_step_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    next_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentExecutionStep(Base):
    __tablename__ = "agent_execution_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_index", name="uq_agent_execution_steps_index"),
        Index("ix_agent_execution_steps_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_executions.id", ondelete="RESTRICT"), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
