"""Organization usage budget for one unit in one calendar period (DFR1-017)."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
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
    ``consumed_quantity`` holds settled usage. ``last_alert_percent`` is the highest
    threshold (70, 85 or 100) already announced, so each alert fires once.
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
