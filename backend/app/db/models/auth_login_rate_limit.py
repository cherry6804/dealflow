"""Shared login throttling state across DealFlow API instances."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthLoginRateLimit(Base):
    """A keyed counter for a bounded login rate-limit window."""

    __tablename__ = "auth_login_rate_limits"
    __table_args__ = (Index("ix_auth_login_rate_limits_window", "window_started_at"),)

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
