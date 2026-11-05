"""Stored lead priority results and human corrections (DFR1-020).

A score row is written once and never updated: it records the rule-set version, the time it was computed, the factors it read and
a hash of those facts. A correction is a human judgement recorded against one score for later evaluation. It does not change
the score.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LeadPriorityScore(Base):
    __tablename__ = "lead_priority_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_lead_priority_scores_lead_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_lead_priority_scores_score"),
        CheckConstraint("band IN ('high', 'medium', 'low')", name="ck_lead_priority_scores_band"),
        Index("ix_lead_priority_scores_org_lead_computed", "organization_id", "lead_id", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(60), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(String(10), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    insufficient_data: Mapped[bool] = mapped_column(nullable=False)
    factors: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    missing_factors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    requirement_summary: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LeadPriorityCorrection(Base):
    __tablename__ = "lead_priority_corrections"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_lead_priority_corrections_idempotency"),
        CheckConstraint("corrected_band IS NULL OR corrected_band IN ('high', 'medium', 'low')",
                        name="ck_lead_priority_corrections_band"),
        CheckConstraint("corrected_score IS NULL OR (corrected_score >= 0 AND corrected_score <= 100)",
                        name="ck_lead_priority_corrections_score"),
        Index("ix_lead_priority_corrections_score", "score_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    score_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_priority_scores.id", ondelete="RESTRICT"), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    corrected_band: Mapped[str | None] = mapped_column(String(10), nullable=True)
    corrected_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
