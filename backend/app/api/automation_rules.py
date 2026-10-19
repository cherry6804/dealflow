
"""FastAPI routes for tenant-scoped automation rules and execution audits."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.automation_rules.schemas import (
    AutomationExecutionListResponse,
    AutomationExecutionResponse,
    AutomationRuleCreateRequest,
    AutomationRuleListResponse,
    AutomationRuleResponse,
    AutomationRuleUpdateRequest,
)
from app.automation_rules.service import (
    activate_automation_rule,
    create_automation_rule,
    disable_automation_rule,
    get_automation_rule,
    list_automation_rules,
    update_automation_rule,
)
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext

router = APIRouter(
    prefix="/api/v1/automation-rules",
    tags=["automation-rules"],
)


def _commit_and_refresh(
    db: Session,
    rule: AutomationRule,
) -> AutomationRuleResponse:
    db.commit()
    db.refresh(rule)
    return AutomationRuleResponse.model_validate(rule)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Automation rule not found.",
    )


@router.post(
    "",
    response_model=AutomationRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_automation_rule_endpoint(
    payload: AutomationRuleCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("automation.create")
    ),
    db: Session = Depends(get_db_session),
) -> AutomationRuleResponse:
    """Create a draft automation rule."""
    try:
        rule = create_automation_rule(
            db,
            organization_id=tenant_context.organization_id,
            user_id=tenant_context.membership.user_id,
            payload=payload,
        )
        return _commit_and_refresh(db, rule)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The automation rule could not be saved.",
        ) from exc
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The automation rule could not be saved.",
        ) from None


@router.get(
    "",
    response_model=AutomationRuleListResponse,
)
def list_automation_rules_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(
        default=None,
        alias="status",
    ),
    tenant_context: TenantContext = Depends(
        require_permission("automation.read")
    ),
    db: Session = Depends(get_db_session),
) -> AutomationRuleListResponse:
    """List automation rules for the verified organization."""
    if (
        status_filter is not None
        and status_filter not in AutomationRule.STATUS_VALUES
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid automation rule status.",
        )

    try:
        items, total = list_automation_rules(
            db,
            organization_id=tenant_context.organization_id,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Automation rules could not be listed.",
        ) from None

    return AutomationRuleListResponse(
        items=[
            AutomationRuleResponse.model_validate(item)
            for item in items
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/executions",
    response_model=AutomationExecutionListResponse,
)
def list_automation_executions_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(
        default=None,
        alias="status",
    ),
    rule_id: UUID | None = Query(default=None),
    event_type: str | None = Query(
        default=None,
        min_length=1,
        max_length=100,
    ),
    tenant_context: TenantContext = Depends(
        require_permission("automation.read")
    ),
    db: Session = Depends(get_db_session),
) -> AutomationExecutionListResponse:
    """List automation execution audit records for the verified organization."""
    if (
        status_filter is not None
        and status_filter not in AutomationExecution.STATUS_VALUES
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid automation execution status.",
        )

    if event_type is not None:
        event_type = event_type.strip()
        if not event_type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Event type cannot be blank.",
            )

    # Always apply the organization filter, regardless of other query filters.
    filters = [
        AutomationExecution.organization_id
        == tenant_context.organization_id
    ]

    if status_filter is not None:
        filters.append(AutomationExecution.status == status_filter)

    if rule_id is not None:
        filters.append(AutomationExecution.rule_id == rule_id)

    if event_type is not None:
        filters.append(AutomationExecution.event_type == event_type)

    try:
        total = db.scalar(
            select(func.count())
            .select_from(AutomationExecution)
            .where(*filters)
        ) or 0

        items = db.scalars(
            select(AutomationExecution)
            .where(*filters)
            .order_by(
                AutomationExecution.created_at.desc(),
                AutomationExecution.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Automation execution audit records could not be listed.",
        ) from None

    return AutomationExecutionListResponse(
        items=[
            AutomationExecutionResponse.model_validate(item)
            for item in items
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/{rule_id}",
    response_model=AutomationRuleResponse,
)
def get_automation_rule_endpoint(
    rule_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("automation.read")
    ),
    db: Session = Depends(get_db_session),
) -> AutomationRuleResponse:
    """Get a rule within the verified organization."""
    try:
        rule = get_automation_rule(
            db,
            organization_id=tenant_context.organization_id,
            rule_id=rule_id,
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The automation rule could not be retrieved.",
        ) from None

    if rule is None:
        raise _not_found()

    return AutomationRuleResponse.model_validate(rule)


@router.patch(
    "/{rule_id}",
    response_model=AutomationRuleResponse,
)
def update_automation_rule_endpoint(
    rule_id: UUID,
    payload: AutomationRuleUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("automation.update")
    ),
    db: Session = Depends(get_db_session),
) -> AutomationRuleResponse:
    """Update a non-active rule's configuration."""
    try:
        rule = update_automation_rule(
            db,
            organization_id=tenant_context.organization_id,
            rule_id=rule_id,
            user_id=tenant_context.membership.user_id,
            payload=payload,
        )
        if rule is None:
            db.rollback()
            raise _not_found()

        return _commit_and_refresh(db, rule)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The automation rule could not be updated.",
        ) from exc
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The automation rule could not be updated.",
        ) from None


@router.post(
    "/{rule_id}/activate",
    response_model=AutomationRuleResponse,
)
def activate_automation_rule_endpoint(
    rule_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("automation.update")
    ),
    db: Session = Depends(get_db_session),
) -> AutomationRuleResponse:
    """Activate a validated rule configuration."""
    try:
        rule = activate_automation_rule(
            db,
            organization_id=tenant_context.organization_id,
            rule_id=rule_id,
            user_id=tenant_context.membership.user_id,
        )
        if rule is None:
            db.rollback()
            raise _not_found()

        return _commit_and_refresh(db, rule)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The automation rule could not be activated.",
        ) from None


@router.post(
    "/{rule_id}/disable",
    response_model=AutomationRuleResponse,
)
def disable_automation_rule_endpoint(
    rule_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("automation.update")
    ),
    db: Session = Depends(get_db_session),
) -> AutomationRuleResponse:
    """Disable an active or draft rule."""
    try:
        rule = disable_automation_rule(
            db,
            organization_id=tenant_context.organization_id,
            rule_id=rule_id,
            user_id=tenant_context.membership.user_id,
        )
        if rule is None:
            db.rollback()
            raise _not_found()

        return _commit_and_refresh(db, rule)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The automation rule could not be disabled.",
        ) from None
