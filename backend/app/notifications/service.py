
"""Service operations for tenant-scoped in-app notifications."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.membership import Membership
from app.db.models.notification import Notification
from app.db.models.organization import Organization


def create_notification(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
    event_type: str,
    title: str,
    message: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    event_key: str | None = None,
) -> Notification:
    """Create a notification for an active organization member.

    A stable event_key makes repeated deliveries idempotent for the
    same organization and recipient.
    """
    membership_statement = (
        select(Membership.id)
        .join(
            Organization,
            Organization.id == Membership.organization_id,
        )
        .where(
            Membership.organization_id == organization_id,
            Membership.user_id == recipient_user_id,
            Membership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
    )

    if db.scalar(membership_statement) is None:
        raise ValueError(
            "Notification recipient must be an active member "
            "of an active organization."
        )

    if event_key is not None:
        existing = db.scalar(
            select(Notification).where(
                Notification.organization_id == organization_id,
                Notification.recipient_user_id == recipient_user_id,
                Notification.event_key == event_key,
            )
        )
        if existing is not None:
            return existing

    notification = Notification(
        organization_id=organization_id,
        recipient_user_id=recipient_user_id,
        event_type=event_type,
        title=title,
        message=message,
        resource_type=resource_type,
        resource_id=resource_id,
        event_key=event_key,
    )

    if event_key is None:
        db.add(notification)
        db.flush()
        db.refresh(notification)
        return notification

    try:
        with db.begin_nested():
            db.add(notification)
            db.flush()
    except IntegrityError:
        # A concurrent event delivery may have inserted this event first.
        existing = db.scalar(
            select(Notification).where(
                Notification.organization_id == organization_id,
                Notification.recipient_user_id == recipient_user_id,
                Notification.event_key == event_key,
            )
        )
        if existing is not None:
            return existing
        raise

    db.refresh(notification)
    return notification


def list_notifications(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Notification], int, int]:
    """List a user's notifications and return total and unread counts."""
    filters = (
        Notification.organization_id == organization_id,
        Notification.recipient_user_id == recipient_user_id,
    )

    items = list(
        db.scalars(
            select(Notification)
            .where(*filters)
            .order_by(
                Notification.created_at.desc(),
                Notification.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )

    total = int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(*filters)
        )
        or 0
    )

    unread_count = int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                *filters,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )

    return items, total, unread_count


def count_unread_notifications(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
) -> int:
    """Count unread notifications for one user in one organization."""
    statement = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.organization_id == organization_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )
    )
    return int(db.scalar(statement) or 0)


def mark_notification_read(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
    notification_id: UUID,
) -> Notification | None:
    """Mark a notification as read if it belongs to the current user."""
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.organization_id == organization_id,
            Notification.recipient_user_id == recipient_user_id,
        )
    )

    if notification is None:
        return None

    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.flush()
        db.refresh(notification)

    return notification


def mark_all_notifications_read(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
) -> int:
    """Mark all unread notifications for the current user as read."""
    statement = (
        update(Notification)
        .where(
            Notification.organization_id == organization_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )

    result = db.execute(statement)
    db.flush()
    return int(result.rowcount or 0)
