
"""FastAPI routes for tenant-scoped in-app notifications."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.notifications.schemas import (
    NotificationListResponse,
    NotificationMarkAllReadResponse,
    NotificationResponse,
    NotificationUnreadCountResponse,
)
from app.notifications.service import (
    count_unread_notifications,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["notifications"],
)


@router.get(
    "",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
)
def list_notifications_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> NotificationListResponse:
    """List notifications for the authenticated user in the active tenant."""
    items, total, unread_count = list_notifications(
        db=db,
        organization_id=tenant_context.organization_id,
        recipient_user_id=tenant_context.membership.user_id,
        limit=limit,
        offset=offset,
    )

    return NotificationListResponse(
        items=[
            NotificationResponse.model_validate(item)
            for item in items
        ],
        total=total,
        unread_count=unread_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/unread-count",
    response_model=NotificationUnreadCountResponse,
    status_code=status.HTTP_200_OK,
)
def unread_notification_count_endpoint(
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> NotificationUnreadCountResponse:
    """Return the unread notification count for the authenticated user."""
    unread_count = count_unread_notifications(
        db=db,
        organization_id=tenant_context.organization_id,
        recipient_user_id=tenant_context.membership.user_id,
    )

    return NotificationUnreadCountResponse(
        unread_count=unread_count,
    )


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
)
def mark_notification_read_endpoint(
    notification_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> NotificationResponse:
    """Mark one of the current user's notifications as read."""
    notification = mark_notification_read(
        db=db,
        organization_id=tenant_context.organization_id,
        recipient_user_id=tenant_context.membership.user_id,
        notification_id=notification_id,
    )

    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    db.commit()
    db.refresh(notification)

    return NotificationResponse.model_validate(notification)


@router.post(
    "/mark-all-read",
    response_model=NotificationMarkAllReadResponse,
    status_code=status.HTTP_200_OK,
)
def mark_all_notifications_read_endpoint(
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> NotificationMarkAllReadResponse:
    """Mark all of the current user's unread notifications as read."""
    updated_count = mark_all_notifications_read(
        db=db,
        organization_id=tenant_context.organization_id,
        recipient_user_id=tenant_context.membership.user_id,
    )

    db.commit()

    return NotificationMarkAllReadResponse(
        updated_count=updated_count,
    )
