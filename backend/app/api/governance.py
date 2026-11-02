"""Organization AI and automation capability settings (DFR1-006)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.dependencies import permission_granted, require_permission
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest
from app.db.session import get_db_session
from app.governance.capabilities import CapabilityCategory
from app.governance.data_classification import CATEGORIES
from app.governance.privacy import (
    InvalidRequestStateError,
    UnknownCategoryError,
    cancel_request,
    create_privacy_request,
    current_retention,
    expire_export_if_due,
    place_legal_hold,
    release_legal_hold,
    set_retention_policy,
)
from app.governance.service import (
    CapabilityState,
    UnknownCapabilityError,
    list_capability_states,
    set_capability_enabled,
)
from app.governance.usage_ledger import (
    UsageUnit,
    budget_period_for,
    budget_status,
    change_budget,
)
from app.tenant.dependencies import TenantContext, get_tenant_context

# Handlers are defined once here and mounted under two prefixes (ADR-0031).
governance_routes = APIRouter(tags=["governance"])


class CapabilityDecisionResponse(BaseModel):
    allowed: bool
    reason_code: str
    explanation: str
    policy_version: int


class CapabilityStateResponse(BaseModel):
    """One governed capability. ``effective`` is the engine's answer, not the switch alone."""

    model_config = ConfigDict(frozen=True)

    capability_key: str
    category: CapabilityCategory
    parent_key: str | None
    is_enabled: bool
    policy_version: int
    updated_at: datetime | None
    effective: CapabilityDecisionResponse


class CapabilityListResponse(BaseModel):
    items: list[CapabilityStateResponse]


class CapabilityUpdateRequest(BaseModel):
    is_enabled: bool = Field(...)
    confirm: Literal[True] = Field(
        ...,
        description="Must be true. Confirms the consequential change.",
    )


def _state_response(state: CapabilityState) -> CapabilityStateResponse:
    return CapabilityStateResponse(
        capability_key=state.definition.key,
        category=state.definition.category,
        parent_key=state.definition.parent_key,
        is_enabled=state.is_enabled,
        policy_version=state.policy_version,
        updated_at=state.updated_at,
        effective=CapabilityDecisionResponse(
            allowed=state.decision.allowed,
            reason_code=state.decision.reason_code,
            explanation=state.decision.explanation,
            policy_version=state.decision.policy_version,
        ),
    )


@governance_routes.get("/capabilities", response_model=CapabilityListResponse)
def get_capability_settings(
    tenant: TenantContext = Depends(require_permission("governance.capabilities.read")),
    db: Session = Depends(get_db_session),
) -> CapabilityListResponse:
    """List every governed capability for the selected organization."""
    return CapabilityListResponse(
        items=[
            _state_response(state)
            for state in list_capability_states(db, organization_id=tenant.organization_id)
        ]
    )


@governance_routes.patch("/capabilities/{capability_key}", response_model=CapabilityStateResponse)
def update_capability_setting(
    capability_key: str,
    payload: CapabilityUpdateRequest,
    tenant: TenantContext = Depends(require_permission("governance.capabilities.manage")),
    db: Session = Depends(get_db_session),
) -> CapabilityStateResponse:
    """Turn one capability on or off. Owner-only. Writes an audit event."""
    try:
        state = set_capability_enabled(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            capability_key=capability_key,
            is_enabled=payload.is_enabled,
            correlation_id=str(uuid4()),
        )
        db.commit()
    except UnknownCapabilityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Capability not found.",
        ) from None
    return _state_response(state)


# ---------------------------------------------------------------------------
# AI usage budgets (DFR1-017)
# ---------------------------------------------------------------------------


class BudgetStatusResponse(BaseModel):
    unit: str
    period_start: date
    period_end: date
    limit_quantity: int
    reserved_quantity: int
    consumed_quantity: int
    remaining_quantity: int
    utilization_percent: int
    overrun: bool


class BudgetListResponse(BaseModel):
    period_start: date
    period_end: date
    items: list[BudgetStatusResponse]


class BudgetUpdateRequest(BaseModel):
    limit_quantity: int = Field(..., ge=0)
    confirm: Literal[True] = Field(..., description="Must be true. Confirms the consequential change.")


def _budget_response(result) -> BudgetStatusResponse:
    return BudgetStatusResponse(
        unit=result.unit,
        period_start=result.period_start,
        period_end=result.period_end,
        limit_quantity=result.limit_quantity,
        reserved_quantity=result.reserved_quantity,
        consumed_quantity=result.consumed_quantity,
        remaining_quantity=result.remaining_quantity,
        utilization_percent=result.utilization_percent,
        overrun=result.overrun,
    )


@governance_routes.get("/usage/budgets", response_model=BudgetListResponse)
def get_usage_budgets(
    tenant: TenantContext = Depends(require_permission("governance.usage.read")),
    db: Session = Depends(get_db_session),
) -> BudgetListResponse:
    """Budget status for every unit that has a budget in the current UTC month."""
    moment = datetime.now(UTC)
    period = budget_period_for(moment)
    items: list[BudgetStatusResponse] = []
    for unit in UsageUnit:
        result = budget_status(db, organization_id=tenant.organization_id, unit=unit, moment=moment)
        if result is not None:
            items.append(_budget_response(result))
    return BudgetListResponse(period_start=period.start, period_end=period.end, items=items)


@governance_routes.put("/usage/budgets/{unit}", response_model=BudgetStatusResponse)
def set_usage_budget(
    unit: str,
    payload: BudgetUpdateRequest,
    tenant: TenantContext = Depends(require_permission("governance.budgets.manage")),
    db: Session = Depends(get_db_session),
) -> BudgetStatusResponse:
    """Set the current-month limit for one unit. Owner-only. Writes an audit event."""
    try:
        usage_unit = UsageUnit(unit)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usage unit not found.") from None
    moment = datetime.now(UTC)
    change_budget(
        db,
        organization_id=tenant.organization_id,
        actor_user_id=tenant.membership.user_id,
        unit=usage_unit,
        limit_quantity=payload.limit_quantity,
        moment=moment,
    )
    db.commit()
    result = budget_status(db, organization_id=tenant.organization_id, unit=usage_unit, moment=moment)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found.")
    return _budget_response(result)


# ---------------------------------------------------------------------------
# Privacy: retention, legal holds, export and deletion requests (DFR1-050)
# ---------------------------------------------------------------------------


class DataCategoryResponse(BaseModel):
    category_key: str
    label: str
    sensitivity: str
    retention_treatment: str
    producer_exists: bool
    note: str


class RetentionPolicyResponse(BaseModel):
    category_key: str
    retention_days: int | None
    version: int | None


class RetentionUpdateRequest(BaseModel):
    retention_days: int | None = Field(default=None, ge=1, le=36500)
    confirm: Literal[True] = Field(..., description="Must be true. Confirms the consequential change.")


class LegalHoldCreateRequest(BaseModel):
    category_key: str = Field(..., min_length=1, max_length=100)
    reason: str = Field(..., min_length=1, max_length=500)
    confirm: Literal[True] = Field(...)


class LegalHoldResponse(BaseModel):
    id: UUID
    category_key: str
    reason: str
    placed_at: datetime
    released_at: datetime | None


class PrivacyRequestCreate(BaseModel):
    request_type: Literal["export", "deletion"]
    categories: list[str] = Field(..., min_length=1, max_length=20)
    confirm: Literal[True] = Field(...)


class PrivacyRequestResponse(BaseModel):
    id: UUID
    request_type: str
    status: str
    categories: list[str]
    decisions: dict[str, object]
    artifact_reference: str | None
    expires_at: datetime | None
    created_at: datetime


def _category_response(category) -> DataCategoryResponse:
    return DataCategoryResponse(
        category_key=category.key,
        label=category.label,
        sensitivity=category.sensitivity.value,
        retention_treatment=category.retention.value,
        producer_exists=category.producer_exists,
        note=category.note,
    )


def _hold_response(hold) -> LegalHoldResponse:
    return LegalHoldResponse(
        id=hold.id,
        category_key=hold.category_key,
        reason=hold.reason,
        placed_at=hold.placed_at,
        released_at=hold.released_at,
    )


def _request_response(row) -> PrivacyRequestResponse:
    return PrivacyRequestResponse(
        id=row.id,
        request_type=row.request_type,
        status=row.status,
        categories=json.loads(row.categories),
        decisions=json.loads(row.decisions),
        artifact_reference=row.artifact_reference,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


@governance_routes.get("/privacy/categories", response_model=list[DataCategoryResponse])
def list_data_categories(
    tenant: TenantContext = Depends(require_permission("governance.privacy.read")),
) -> list[DataCategoryResponse]:
    """The data classification register, including categories with no producer yet."""
    return [_category_response(category) for category in CATEGORIES]


@governance_routes.get("/privacy/retention", response_model=list[RetentionPolicyResponse])
def list_retention_policies(
    tenant: TenantContext = Depends(require_permission("governance.privacy.read")),
    db: Session = Depends(get_db_session),
) -> list[RetentionPolicyResponse]:
    responses: list[RetentionPolicyResponse] = []
    for category in CATEGORIES:
        policy = current_retention(db, organization_id=tenant.organization_id, category_key=category.key)
        responses.append(
            RetentionPolicyResponse(
                category_key=category.key,
                retention_days=policy.retention_days if policy else None,
                version=policy.version if policy else None,
            )
        )
    return responses


@governance_routes.put("/privacy/retention/{category_key}", response_model=RetentionPolicyResponse)
def update_retention_policy(
    category_key: str,
    payload: RetentionUpdateRequest,
    tenant: TenantContext = Depends(require_permission("governance.privacy.manage")),
    db: Session = Depends(get_db_session),
) -> RetentionPolicyResponse:
    try:
        policy = set_retention_policy(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            category_key=category_key,
            retention_days=payload.retention_days,
        )
    except UnknownCategoryError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data category not found.") from None
    db.commit()
    return RetentionPolicyResponse(
        category_key=category_key,
        retention_days=policy.retention_days,
        version=policy.version,
    )


@governance_routes.post("/privacy/legal-holds", response_model=LegalHoldResponse, status_code=status.HTTP_201_CREATED)
def create_legal_hold(
    payload: LegalHoldCreateRequest,
    tenant: TenantContext = Depends(require_permission("governance.privacy.manage")),
    db: Session = Depends(get_db_session),
) -> LegalHoldResponse:
    try:
        hold = place_legal_hold(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            category_key=payload.category_key,
            reason=payload.reason,
        )
    except UnknownCategoryError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data category not found.") from None
    db.commit()
    return _hold_response(hold)


@governance_routes.post("/privacy/legal-holds/{hold_id}/release", response_model=LegalHoldResponse)
def end_legal_hold(
    hold_id: UUID,
    tenant: TenantContext = Depends(require_permission("governance.privacy.manage")),
    db: Session = Depends(get_db_session),
) -> LegalHoldResponse:
    try:
        hold = release_legal_hold(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            hold_id=hold_id,
        )
    except InvalidRequestStateError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal hold not found.") from None
    db.commit()
    return _hold_response(hold)


@governance_routes.get("/privacy/requests", response_model=list[PrivacyRequestResponse])
def list_privacy_requests(
    tenant: TenantContext = Depends(require_permission("governance.privacy.read")),
    db: Session = Depends(get_db_session),
) -> list[PrivacyRequestResponse]:
    rows = db.scalars(
        select(PrivacyDataRequest)
        .where(PrivacyDataRequest.organization_id == tenant.organization_id)
        .order_by(PrivacyDataRequest.created_at.desc())
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        expire_export_if_due(db, request=row, now=now)
    db.commit()
    return [_request_response(row) for row in rows]


@governance_routes.post("/privacy/requests", response_model=PrivacyRequestResponse, status_code=status.HTTP_201_CREATED)
def create_privacy_request_endpoint(
    payload: PrivacyRequestCreate,
    tenant: TenantContext = Depends(require_permission("governance.privacy.manage")),
    db: Session = Depends(get_db_session),
) -> PrivacyRequestResponse:
    try:
        row = create_privacy_request(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            request_type=payload.request_type,
            category_keys=payload.categories,
        )
    except UnknownCategoryError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data category not found.") from None
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None
    db.commit()
    return _request_response(row)


@governance_routes.post("/privacy/requests/{request_id}/cancel", response_model=PrivacyRequestResponse)
def cancel_privacy_request(
    request_id: UUID,
    tenant: TenantContext = Depends(require_permission("governance.privacy.manage")),
    db: Session = Depends(get_db_session),
) -> PrivacyRequestResponse:
    try:
        row = cancel_request(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            request_id=request_id,
        )
    except InvalidRequestStateError as error:
        db.rollback()
        not_found = "not found" in str(error)
        code = status.HTTP_404_NOT_FOUND if not_found else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=str(error)) from None
    db.commit()
    return _request_response(row)


@governance_routes.get("/privacy/legal-holds", response_model=list[LegalHoldResponse])
def list_legal_holds(
    tenant: TenantContext = Depends(require_permission("governance.privacy.read")),
    db: Session = Depends(get_db_session),
) -> list[LegalHoldResponse]:
    rows = db.scalars(
        select(LegalHold)
        .where(LegalHold.organization_id == tenant.organization_id)
        .order_by(LegalHold.placed_at.desc())
    ).all()
    return [_hold_response(row) for row in rows]


class GovernanceAccessResponse(BaseModel):
    """Which governance permissions the caller holds. Used to shape the UI only.

    The server enforces every action again on each request.
    """

    capabilities_read: bool
    capabilities_manage: bool
    usage_read: bool
    budgets_manage: bool
    privacy_read: bool
    privacy_manage: bool


@governance_routes.get("/access", response_model=GovernanceAccessResponse)
def get_governance_access(
    tenant: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> GovernanceAccessResponse:
    def granted(permission_key: str) -> bool:
        return permission_granted(db, tenant_context=tenant, permission_key=permission_key)

    return GovernanceAccessResponse(
        capabilities_read=granted("governance.capabilities.read"),
        capabilities_manage=granted("governance.capabilities.manage"),
        usage_read=granted("governance.usage.read"),
        budgets_manage=granted("governance.budgets.manage"),
        privacy_read=granted("governance.privacy.read"),
        privacy_manage=granted("governance.privacy.manage"),
    )


# Canonical AI namespace (ADR-0031). Visible in OpenAPI.
canonical_router = APIRouter(tags=["governance"])
canonical_router.include_router(governance_routes, prefix="/api/v1/ai/governance")

# Legacy alias for existing consumers (ADR-0031). Same handlers, hidden from OpenAPI.
router = APIRouter(tags=["governance"])
router.include_router(governance_routes, prefix="/api/v1/governance", include_in_schema=False)
