"""Lead intake submissions and qualification results (DFR1-021).

A submission keeps what was received, exactly as received, next to what the CRM understood from it. The raw payload is never
edited. The normalized payload, the identity candidates and the outcome are recorded beside it, so a reviewer can see both.

A qualification result is written once per agent execution. It separates verified CRM facts, rule findings, missing information,
AI suggestions and human decisions. A human review changes only the review fields of the result, never the lead.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LeadIntakeSubmission(Base):
    __tablename__ = "lead_intake_submissions"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_reference", name="uq_lead_intake_submissions_reference"),
        CheckConstraint(
            "status IN ('invalid', 'received', 'needs_review', 'processed', 'rejected')",
            name="ck_lead_intake_submissions_status",
        ),
        CheckConstraint(
            "source_channel IN ('manual', 'form', 'api')",
            name="ck_lead_intake_submissions_channel",
        ),
        Index("ix_lead_intake_submissions_org_status", "organization_id", "status"),
    )

    STATUS_INVALID = "invalid"
    STATUS_RECEIVED = "received"
    STATUS_NEEDS_REVIEW = "needs_review"
    STATUS_PROCESSED = "processed"
    STATUS_REJECTED = "rejected"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    source_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    normalized_payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    validation_problems: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    match_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    candidate_contact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LeadQualificationResult(Base):
    __tablename__ = "lead_qualification_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_lead_qualification_results_lead_org",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", name="uq_lead_qualification_results_execution"),
        CheckConstraint("review_status IN ('pending', 'accepted', 'overridden')",
                        name="ck_lead_qualification_results_review"),
        Index("ix_lead_qualification_results_org_lead", "organization_id", "lead_id", "created_at"),
    )

    REVIEW_PENDING = "pending"
    REVIEW_ACCEPTED = "accepted"
    REVIEW_OVERRIDDEN = "overridden"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_executions.id", ondelete="RESTRICT"), nullable=False)
    score_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_priority_scores.id", ondelete="RESTRICT"), nullable=False)
    findings: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lead_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    review_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
