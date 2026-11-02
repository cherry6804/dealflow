"""Organization AI usage alert thresholds: defaults, validation and storage (WS6 WP2).

An organization chooses three percentages. An alert is announced when usage first reaches each one.
The rules are enforced here, on the server:

- exactly three values;
- each a whole number from 1 to 100, not a boolean;
- strictly increasing, so no duplicates and no reordering;
- the highest value is 100, so the final alert still means the budget is exhausted.

Without a stored row, an organization uses the defaults 70, 85 and 100. Nothing here changes a
budget amount, a price, a plan or a usage unit. This module does not import the usage ledger.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.organization_usage_alert_settings import (
    OrganizationUsageAlertSettings,
)

DEFAULT_ALERT_THRESHOLDS: tuple[int, int, int] = (70, 85, 100)
REQUIRED_TOP_THRESHOLD = 100
MIN_THRESHOLD = 1
MAX_THRESHOLD = 100

REASON_WRONG_COUNT = "wrong_count"
REASON_NOT_A_WHOLE_NUMBER = "not_a_whole_number"
REASON_OUT_OF_RANGE = "out_of_range"
REASON_NOT_STRICTLY_INCREASING = "not_strictly_increasing"
REASON_TOP_NOT_100 = "top_threshold_must_be_100"

_MESSAGES = {
    REASON_WRONG_COUNT: "Enter exactly three alert thresholds.",
    REASON_NOT_A_WHOLE_NUMBER: "Each alert threshold must be a whole number.",
    REASON_OUT_OF_RANGE: "Each alert threshold must be from 1 to 100.",
    REASON_NOT_STRICTLY_INCREASING: "Alert thresholds must increase, with no duplicates.",
    REASON_TOP_NOT_100: "The highest alert threshold must be 100.",
}


class InvalidAlertThresholdsError(ValueError):
    """The requested thresholds break a rule. ``reason_code`` is stable and safe to show."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(_MESSAGES[reason_code])
        self.reason_code = reason_code
        self.message = _MESSAGES[reason_code]


@dataclass(frozen=True)
class AlertThresholds:
    values: tuple[int, int, int]
    is_default: bool
    version: int
    updated_at: datetime | None


def validate_alert_thresholds(values: Sequence[object]) -> tuple[int, int, int]:
    """Return the thresholds as a typed tuple, or raise ``InvalidAlertThresholdsError``."""
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise InvalidAlertThresholdsError(REASON_WRONG_COUNT)
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidAlertThresholdsError(REASON_NOT_A_WHOLE_NUMBER)
        if not MIN_THRESHOLD <= value <= MAX_THRESHOLD:
            raise InvalidAlertThresholdsError(REASON_OUT_OF_RANGE)
    low, mid, high = values
    if not low < mid < high:
        raise InvalidAlertThresholdsError(REASON_NOT_STRICTLY_INCREASING)
    if high != REQUIRED_TOP_THRESHOLD:
        raise InvalidAlertThresholdsError(REASON_TOP_NOT_100)
    return (low, mid, high)


def _row(db: Session, organization_id: UUID) -> OrganizationUsageAlertSettings | None:
    return db.scalar(
        select(OrganizationUsageAlertSettings).where(
            OrganizationUsageAlertSettings.organization_id == organization_id
        )
    )


def read_alert_thresholds(db: Session, *, organization_id: UUID) -> AlertThresholds:
    """The organization's thresholds, or the defaults when it has never changed them."""
    row = _row(db, organization_id)
    if row is None:
        return AlertThresholds(values=DEFAULT_ALERT_THRESHOLDS, is_default=True, version=0, updated_at=None)
    return AlertThresholds(
        values=(row.threshold_low, row.threshold_mid, row.threshold_high),
        is_default=False,
        version=row.version,
        updated_at=row.updated_at,
    )


def store_alert_thresholds(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    values: tuple[int, int, int],
) -> None:
    """Insert or replace the organization's row. Concurrent first writes resolve by upsert.

    The caller owns the transaction and has already validated ``values``.
    """
    low, mid, high = values
    statement = pg_insert(OrganizationUsageAlertSettings.__table__).values(
        organization_id=organization_id,
        threshold_low=low,
        threshold_mid=mid,
        threshold_high=high,
        version=1,
        updated_by_user_id=actor_user_id,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[OrganizationUsageAlertSettings.__table__.c.organization_id],
        set_={
            "threshold_low": low,
            "threshold_mid": mid,
            "threshold_high": high,
            "version": OrganizationUsageAlertSettings.__table__.c.version + 1,
            "updated_by_user_id": actor_user_id,
            "updated_at": func.now(),
        },
    )
    db.execute(statement)
    db.flush()
