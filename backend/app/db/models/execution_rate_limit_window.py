"""Fixed-window request counter for execution rate limits (E13 hardening).

A row counts governed executions for one scope (organization or actor) and one execution type
within one window. It is a request counter, not a usage ledger: it records no tokens, cost or
provider usage. Usage is recorded only by the E13 usage ledger.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExecutionRateLimitWindow(Base):
    """One scope's counter for one execution type in its current window."""

    __tablename__ = "execution_rate_limit_windows"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "scope_type",
            "scope_id",
            "execution_type",
            name="uq_execution_rate_limit_windows_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_type: Mapped[str] = mapped_column(String(80), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
