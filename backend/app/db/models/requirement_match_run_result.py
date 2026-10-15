
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RequirementMatchRunResult(Base):
    """Immutable snapshot of one property's result in a matching run."""

    __tablename__ = "requirement_match_run_results"

    __table_args__ = (
        ForeignKeyConstraint(
            ["match_run_id", "organization_id"],
            [
                "requirement_match_runs.id",
                "requirement_match_runs.organization_id",
            ],
            name="fk_requirement_match_run_results_run_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "match_run_id",
            "property_id",
            name="uq_requirement_match_run_results_run_property",
        ),
        Index(
            "ix_requirement_match_run_results_org_run",
            "organization_id",
            "match_run_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    match_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    # Deliberately no property FK: historical snapshots should remain
    # available even if the original property is deleted.
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    overall_match: Mapped[bool] = mapped_column(
        nullable=False,
    )

    property_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    criteria_results_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
    )
