"""Organization AI usage alert thresholds (WS6 WP2).

One row per organization, holding three strictly increasing percentages. The top threshold is
always 100 so the final alert still means the budget is exhausted. An organization without a row
uses the defaults 70, 85 and 100, so existing organizations need no backfill.

The row is configuration, not usage. It never changes budget amounts, pricing or usage units.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrganizationUsageAlertSettings(Base):
    __tablename__ = "organization_usage_alert_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_organization_usage_alert_settings_org"),
        CheckConstraint(
            "threshold_low >= 1 AND threshold_low < threshold_mid "
            "AND threshold_mid < threshold_high AND threshold_high = 100",
            name="ck_organization_usage_alert_settings_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    threshold_low: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    threshold_mid: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    threshold_high: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Increases on every change. Included in the audit record.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
