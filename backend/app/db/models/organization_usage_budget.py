"""Organization usage budget for one unit in one calendar period (DFR1-017)."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrganizationUsageBudget(Base):
    """A limit on one usage unit for one organization over one period.

    ``reserved_quantity`` holds quantity promised to in-flight billable work.
    ``consumed_quantity`` holds settled usage. ``alerted_thresholds`` lists every configured
    threshold already covered by a delivered alert for this period, so each alert fires once even
    when the organization changes its thresholds. ``last_alert_percent`` is kept as the highest
    delivered threshold for compatibility with WP1 readers. It is derived, not a source of truth.
    """

    __tablename__ = "organization_usage_budgets"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "unit",
            "period_start",
            name="uq_organization_usage_budgets_org_unit_period",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    limit_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    consumed_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_alert_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A JSON list rather than a PostgreSQL array, so every model compiles on the SQLite engine that some
    # test modules use. Values are whole numbers from 1 to 100, validated before they are stored.
    alerted_thresholds: Mapped[list[int]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
