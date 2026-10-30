
"""Service functions for in-app notifications and notification preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.membership import Membership
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationPreference
from app.db.models.organization import Organization
from app.notifications.schemas import NotificationPreferencesUpdateRequest


# Maps recognized event-type prefixes to their preference category.
_NOTIFICATION_CATEGORY_FIELDS: tuple[tuple[str, str], ...] = (
    ("FOLLOW_UP", "follow_ups_enabled"),
    ("FOLLOWUP", "follow_ups_enabled"),
    ("DEAL", "deals_enabled"),
    ("SITE_VISIT", "site_visits_enabled"),
    ("SITEVISIT", "site_visits_enabled"),
    ("LEAD", "leads_enabled"),
    ("AUTOMATION", "automation_enabled"),
)


def _get_notification_category_field(event_type: str) -> str | None:
    """Return the preference field corresponding to a recognized event type."""

    normalized_event_type = (
        event_type.strip().upper().replace("-", "_").replace(" ", "_")
    )

    for prefix, field_name in _NOTIFICATION_CATEGORY_FIELDS:
        if normalized_event_type == prefix or normalized_event_type.startswith(
            f"{prefix}_"
        ):
            return field_name

    return None


def get_or_create_notification_preferences(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> NotificationPreference:
    """Return preferences for a user in an organization, creating defaults if needed."""

    existing = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.organization_id == organization_id,
            NotificationPreference.user_id == user_id,
        )
    )
    if existing is not None:
        return existing

    preference = NotificationPreference(
        organization_id=organization_id,
        user_id=user_id,
    )

    try:
        # Save inside a savepoint so a concurrent insert does not invalidate
        # the caller's surrounding transaction.
        with db.begin_nested():
            db.add(preference)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(NotificationPreference).where(
                NotificationPreference.organization_id == organization_id,
                NotificationPreference.user_id == user_id,
            )
        )
        if existing is None:
            raise
        return existing

    db.refresh(preference)
    return preference


def update_notification_preferences(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    changes: NotificationPreferencesUpdateRequest,
) -> NotificationPreference:
    """Update only the preference fields explicitly supplied by the user."""

    preference = get_or_create_notification_preferences(
        db,
        organization_id=organization_id,
        user_id=user_id,
    )

    for field_name, value in changes.model_dump(exclude_unset=True).items():
        setattr(preference, field_name, value)

    db.flush()
    db.refresh(preference)
    return preference


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
) -> Notification | None:
    """Create a notification unless the recipient has disabled it.

    The caller controls transaction commit/rollback. An existing notification
    with the same event key is returned before preferences are checked, making
    duplicate-event handling stable if preferences change later.
    """

    membership_exists = db.scalar(
        select(Membership.id)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(
            Membership.organization_id == organization_id,
            Membership.user_id == recipient_user_id,
            Membership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .limit(1)
    )

    if membership_exists is None:
        raise ValueError(
            "Cannot create a notification without an active organization "
            "and an active membership for the recipient."
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

    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.organization_id == organization_id,
            NotificationPreference.user_id == recipient_user_id,
        )
    )

    if preference is not None:
        if not preference.enabled:
            return None

        category_field = _get_notification_category_field(event_type)
        if (
            category_field is not None
            and not getattr(preference, category_field)
        ):
            return None

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
    """Return paginated notifications, total count, and unread count."""

    base_query = select(Notification).where(
        Notification.organization_id == organization_id,
        Notification.recipient_user_id == recipient_user_id,
    )

    total = db.scalar(
        select(func.count()).select_from(base_query.subquery())
    ) or 0

    unread_count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.organization_id == organization_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )
    ) or 0

    items = list(
        db.scalars(
            base_query.order_by(
                Notification.created_at.desc(),
                Notification.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )

    return items, total, unread_count


def count_unread_notifications(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
) -> int:
    """Return the number of unread notifications for a recipient."""

    return db.scalar(
        select(func.count(Notification.id)).where(
            Notification.organization_id == organization_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )
    ) or 0


def mark_notification_read(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
    notification_id: UUID,
) -> Notification | None:
    """Mark a recipient's notification as read, if it belongs to that recipient."""

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
    """Mark all unread notifications for a recipient as read."""

    result = db.execute(
        update(Notification)
        .where(
            Notification.organization_id == organization_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )

    return result.rowcount or 0
