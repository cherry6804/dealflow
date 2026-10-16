"""FastAPI routes for DealFlow site visits."""

from __future__ import annotations

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.models.follow_up import FollowUp
from app.db.session import get_db_session
from app.follow_ups.schemas import FollowUpCreateRequest, FollowUpResponse
from app.follow_ups.service import create_site_visit_follow_up
from app.site_visits.schemas import (
    SiteVisitAttendanceRequest,
    SiteVisitCreateRequest,
    SiteVisitListResponse,
    SiteVisitResponse,
)
from app.site_visits.service import (
    create_site_visit,
    list_site_visits,
    record_site_visit_attendance,
)
from app.tenant.dependencies import TenantContext
router = APIRouter(prefix="/api/v1/site-visits", tags=["site-visits"])


@router.get("", response_model=SiteVisitListResponse)
def list_site_visits_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    tenant_context: TenantContext = Depends(require_permission("leads.update")),
    db: Session = Depends(get_db_session),
) -> SiteVisitListResponse:
    """List site visits belonging only to the verified organization."""
    try:
        items, total = list_site_visits(
            db,
            organization_id=tenant_context.organization_id,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    visit_ids = [item.id for item in items]

    linked_visit_ids: set[UUID] = set()

    if visit_ids:
        statement = select(FollowUp.site_visit_id).where(
            FollowUp.organization_id == tenant_context.organization_id,
            FollowUp.site_visit_id.in_(visit_ids),
        )

        linked_visit_ids = {
            visit_id
            for visit_id in db.scalars(statement).all()
            if visit_id is not None
        }

    response_items = []

    for item in items:
        response = SiteVisitResponse.model_validate(item)
        response.has_follow_up = item.id in linked_visit_ids
        response_items.append(response)

    return SiteVisitListResponse(
        items=response_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=SiteVisitResponse, status_code=status.HTTP_201_CREATED)
def schedule_site_visit_endpoint(
    payload: SiteVisitCreateRequest,
    tenant_context: TenantContext = Depends(require_permission("leads.update")),
    db: Session = Depends(get_db_session),
) -> SiteVisitResponse:
    """Schedule a site visit within the verified organization."""
    try:
        site_visit = create_site_visit(
            db=db,
            organization_id=tenant_context.organization_id,
            current_user_id=tenant_context.membership.user_id,
            payload=payload,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if site_visit is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property or customer reference not found.",
        )

    try:
        db.commit()
        db.refresh(site_visit)
    except Exception:
        db.rollback()
        raise

    return SiteVisitResponse.model_validate(site_visit)


@router.patch(
    "/{site_visit_id}/attendance",
    response_model=SiteVisitResponse,
)
def record_site_visit_attendance_endpoint(
    site_visit_id: UUID,
    payload: SiteVisitAttendanceRequest,
    tenant_context: TenantContext = Depends(
        require_permission("leads.update")
    ),
    db: Session = Depends(get_db_session),
) -> SiteVisitResponse:
    """Record visit attendance and customer outcome within the active tenant."""
    try:
        site_visit = record_site_visit_attendance(
            db=db,
            organization_id=tenant_context.organization_id,
            site_visit_id=site_visit_id,
            payload=payload,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if site_visit is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site visit not found.",
        )

    try:
        db.commit()
        db.refresh(site_visit)
    except Exception:
        db.rollback()
        raise

    return SiteVisitResponse.model_validate(site_visit)

@router.post(
    "/{site_visit_id}/follow-up",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_site_visit_follow_up_endpoint(
    site_visit_id: UUID,
    payload: FollowUpCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("leads.update")
    ),
    db: Session = Depends(get_db_session),
) -> FollowUpResponse:
    """Create a follow-up from an eligible site visit."""
    try:
        follow_up = create_site_visit_follow_up(
            db=db,
            organization_id=tenant_context.organization_id,
            current_user_id=tenant_context.membership.user_id,
            site_visit_id=site_visit_id,
            payload=payload,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if follow_up is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Site visit or linked lead not found.",
        )

    try:
        db.commit()
        db.refresh(follow_up)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A follow-up already exists for this site visit.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return FollowUpResponse.model_validate(follow_up)