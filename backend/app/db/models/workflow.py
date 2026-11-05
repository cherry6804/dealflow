"""Workflow definitions, immutable published versions and lifecycle history (DFR1-023).

A workflow definition has one mutable draft and any number of published versions. A published version is written once and is never
updated or deleted: the database rejects both, and the service has no path that changes one. The definition points at its current
version. Rollback moves that pointer to an earlier version; it never rewrites a version. Lifecycle events are append-only.

Workflow definitions are kept apart from agent definitions. A workflow references agents by identifier, and only the publish checks
read them.
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


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_workflow_definitions_organization_name"),
        CheckConstraint(
            "status IN ('draft', 'published', 'paused', 'archived')",
            name="ck_workflow_definitions_status",
        ),
        Index("ix_workflow_definitions_organization_id", "organization_id"),
    )

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_PAUSED = "paused"
    STATUS_ARCHIVED = "archived"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_DRAFT)
    draft_configuration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version_number", name="uq_workflow_versions_number"),
        UniqueConstraint("id", "organization_id", name="uq_workflow_versions_id_organization"),
        Index("ix_workflow_versions_organization_workflow", "organization_id", "workflow_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    required_permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    agent_references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    published_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkflowLifecycleEvent(Base):
    __tablename__ = "workflow_lifecycle_events"
    __table_args__ = (
        Index("ix_workflow_lifecycle_events_workflow", "organization_id", "workflow_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    target_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# The same immutability trigger the migration creates, so a database built from the models refuses the same writes.
_IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION workflow_versions_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'workflow versions are immutable';
END;
$$ LANGUAGE plpgsql
"""
_IMMUTABLE_TRIGGER = """
CREATE TRIGGER trg_workflow_versions_immutable
BEFORE UPDATE OR DELETE ON workflow_versions
FOR EACH ROW EXECUTE FUNCTION workflow_versions_immutable()
"""
# Only PostgreSQL supports this trigger. Other dialects (used by some unit tests) skip it.
for _statement in (
    _IMMUTABLE_FUNCTION,
    "DROP TRIGGER IF EXISTS trg_workflow_versions_immutable ON workflow_versions",
    _IMMUTABLE_TRIGGER,
):
    event.listen(WorkflowVersion.__table__, "after_create", DDL(_statement).execute_if(dialect="postgresql"))
