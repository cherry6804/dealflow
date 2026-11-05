"""Next-best-action recommendations from one property matching run (DFR1-022).

A recommendation is created once per matching run and category. It belongs to that run, so it shows the facts it was based on. A
later change to the requirement or the inventory makes the run stale, and the recommendation is then shown as stale rather than
current. Feedback changes only the status and appends to the history; the facts and the summary are never rewritten.
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


class NextBestActionRecommendation(Base):
    __tablename__ = "next_best_action_recommendations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            ["customer_requirements.id", "customer_requirements.organization_id"],
            name="fk_next_best_action_requirement_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["match_run_id", "organization_id"],
            ["requirement_match_runs.id", "requirement_match_runs.organization_id"],
            name="fk_next_best_action_run_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("match_run_id", "category", "subject_key", name="uq_next_best_action_run_category_subject"),
        CheckConstraint(
            "basis IN ('verified_fact', 'deterministic_match', 'missing_information', 'ai_suggestion')",
            name="ck_next_best_action_basis",
        ),
        CheckConstraint("status IN ('open', 'accepted', 'dismissed', 'done')", name="ck_next_best_action_status"),
        Index("ix_next_best_action_org_requirement", "organization_id", "customer_requirement_id"),
    )

    STATUS_OPEN = "open"
    STATUS_ACCEPTED = "accepted"
    STATUS_DISMISSED = "dismissed"
    STATUS_DONE = "done"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    customer_requirement_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    match_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(120), nullable=False)
    basis: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_OPEN)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_property_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(60), nullable=False)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
