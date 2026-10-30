
"""Database model for idempotent automation execution tracking."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutomationExecution(Base):
    """Track one rule's processing of one event within an organization."""

    __tablename__ = "automation_executions"

    STATUS_PENDING = "PENDING"
    STATUS_RUNNING = "RUNNING"
    STATUS_SUCCEEDED = "SUCCEEDED"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_FAILED = "FAILED"
    STATUS_SKIPPED = "SKIPPED"

    STATUS_VALUES = (
        STATUS_PENDING,
        STATUS_RUNNING,
        STATUS_SUCCEEDED,
        STATUS_PARTIAL,
        STATUS_FAILED,
        STATUS_SKIPPED,
    )

    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_automation_executions_id_organization",
        ),
        UniqueConstraint(
            "organization_id",
            "rule_id",
            "event_type",
            "event_id",
            name="uq_automation_execution_event_rule",
        ),
        ForeignKeyConstraint(
            ["rule_id", "organization_id"],
            [
                "automation_rules.id",
                "automation_rules.organization_id",
            ],
            name="fk_automation_execution_rule_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_automation_executions_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN "
            "('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'SKIPPED')",
            name="ck_automation_executions_status",
        ),
        Index(
            "ix_automation_executions_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_automation_executions_org_status",
            "organization_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )

    action_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    error_message: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
