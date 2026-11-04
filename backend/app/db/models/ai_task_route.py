"""Organization-level model and provider selection for one AI task type (DFR1-015).

A row names the provider and model that an organization uses for one task. It never holds a credential: the provider
credential is resolved from ``provider_credentials`` at call time, and only the provider key and the model name are stored.
A missing row means the task has no route, and the gateway refuses it.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TASK_TYPES: tuple[str, ...] = ("text", "embedding", "speech", "multimodal")


class AiTaskRoute(Base):
    __tablename__ = "ai_task_routes"
    __table_args__ = (
        UniqueConstraint("organization_id", "task", name="uq_ai_task_routes_org_task"),
        CheckConstraint(
            "task IN ('text', 'embedding', 'speech', 'multimodal')",
            name="ck_ai_task_routes_task",
        ),
        CheckConstraint(
            "(fallback_provider_key IS NULL) = (fallback_model IS NULL)",
            name="ck_ai_task_routes_fallback_pair",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    # Optional second route, tried only after a transient failure of the primary (DFR1-015 fallback).
    fallback_provider_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fallback_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
