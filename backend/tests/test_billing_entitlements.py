
"""Tests for tenant-scoped billing entitlement enforcement."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.organization import Organization
from app.db.models.plan import Plan
from app.db.models.plan_entitlement import PlanEntitlement
from app.db.models.subscription import Subscription
from app.billing.entitlements import (
    get_accessible_plan,
    get_entitlement_value,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)
    engine.dispose()


def create_subscription(
    db,
    *,
    status=Subscription.STATUS_ACTIVE,
    included_seats=2,
    entitlement_value=True,
    entitlement_key="automation.enabled",
):
    organization = Organization(
        name=f"Test Organization {uuid4()}",
        is_active=True,
    )
    plan = Plan(
        code=f"test-{uuid4().hex}",
        name="Test Plan",
        monthly_price_paise=49900,
        currency="INR",
        included_seats=included_seats,
        is_active=True,
    )
    db.add_all([organization, plan])
    db.flush()

    subscription = Subscription(
        organization_id=organization.id,
        plan_id=plan.id,
        plan_code=plan.code,
        status=status,
        billing_interval="MONTHLY",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc)
        + timedelta(days=30),
    )
    db.add(subscription)

    if entitlement_key is not None:
        db.add(
            PlanEntitlement(
                plan_id=plan.id,
                key=entitlement_key,
                value_type="BOOLEAN",
                value=entitlement_value,
            )
        )

    db.commit()
    return organization, plan, subscription


def test_active_subscription_resolves_entitlement(db):
    organization, plan, _ = create_subscription(db)

    assert get_accessible_plan(
        db,
        organization_id=organization.id,
    ).id == plan.id

    assert get_entitlement_value(
        db,
        organization_id=organization.id,
        key="automation.enabled",
    ) is True


def test_trialing_subscription_allows_access(db):
    organization, _, _ = create_subscription(
        db,
        status=Subscription.STATUS_TRIALING,
    )

    assert get_entitlement_value(
        db,
        organization_id=organization.id,
        key="automation.enabled",
    ) is True


@pytest.mark.parametrize(
    "subscription_status",
    [
        Subscription.STATUS_PENDING,
        Subscription.STATUS_PAST_DUE,
        Subscription.STATUS_PAUSED,
        Subscription.STATUS_CANCELLED,
        Subscription.STATUS_EXPIRED,
    ],
)
def test_ineligible_subscription_status_is_denied(
    db,
    subscription_status,
):
    organization, _, _ = create_subscription(
        db,
        status=subscription_status,
    )

    with pytest.raises(HTTPException) as error:
        get_accessible_plan(
            db,
            organization_id=organization.id,
        )

    assert error.value.status_code == 403


def test_missing_subscription_is_denied(db):
    with pytest.raises(HTTPException) as error:
        get_accessible_plan(
            db,
            organization_id=uuid4(),
        )

    assert error.value.status_code == 403


def test_missing_entitlement_is_denied(db):
    organization, _, _ = create_subscription(
        db,
        entitlement_key=None,
    )

    with pytest.raises(HTTPException) as error:
        get_entitlement_value(
            db,
            organization_id=organization.id,
            key="documents.advanced",
        )

    assert error.value.status_code == 403


def test_disabled_entitlement_returns_false(db):
    organization, _, _ = create_subscription(
        db,
        entitlement_value=False,
    )

    assert get_entitlement_value(
        db,
        organization_id=organization.id,
        key="automation.enabled",
    ) is False


def test_expired_billing_period_is_denied(db):
    organization, _, subscription = create_subscription(db)

    subscription.current_period_end = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    db.commit()

    with pytest.raises(HTTPException) as error:
        get_accessible_plan(
            db,
            organization_id=organization.id,
        )

    assert error.value.status_code == 403


def test_inactive_plan_is_denied(db):
    organization, plan, _ = create_subscription(db)
    plan.is_active = False
    db.commit()

    with pytest.raises(HTTPException) as error:
        get_accessible_plan(
            db,
            organization_id=organization.id,
        )

    assert error.value.status_code == 403


def test_enterprise_unlimited_seats_is_preserved(db):
    organization, plan, _ = create_subscription(
        db,
        included_seats=None,
    )

    assert plan.included_seats is None

    assert get_accessible_plan(
        db,
        organization_id=organization.id,
    ).id == plan.id


def test_entitlements_are_isolated_by_organization(db):
    organization_a, _, _ = create_subscription(db)
    organization_b, _, _ = create_subscription(
        db,
        entitlement_key=None,
    )

    assert get_entitlement_value(
        db,
        organization_id=organization_a.id,
        key="automation.enabled",
    ) is True

    with pytest.raises(HTTPException) as error:
        get_entitlement_value(
            db,
            organization_id=organization_b.id,
            key="automation.enabled",
        )

    assert error.value.status_code == 403
