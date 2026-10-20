from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.plan import Plan
from app.db.models.plan_entitlement import PlanEntitlement
from app.db.models.subscription import Subscription

def test_user_model_fields() -> None:
    user = User(
        email="user@example.com",
        display_name="Test User",
    )

    assert user.id is None
    assert user.email == "user@example.com"
    assert user.display_name == "Test User"
    assert user.is_active is None


def test_organization_model_fields() -> None:
    organization = Organization(
        name="Test Organization",
    )

    assert organization.id is None
    assert organization.name == "Test Organization"
    assert organization.is_active is None


def test_user_model_defaults_are_configured() -> None:
    assert User.__table__.c.id.default is not None
    assert User.__table__.c.is_active.default is not None


def test_organization_model_defaults_are_configured() -> None:
    assert Organization.__table__.c.id.default is not None
    assert Organization.__table__.c.is_active.default is not None

def test_plan_model_fields() -> None:
    plan = Plan(
        code="solo",
        name="Solo",
        monthly_price_paise=49900,
        currency="INR",
        included_seats=1,
    )

    assert plan.id is None
    assert plan.code == "solo"
    assert plan.name == "Solo"
    assert plan.monthly_price_paise == 49900
    assert plan.currency == "INR"
    assert plan.included_seats == 1


def test_enterprise_plan_supports_custom_pricing_and_seats() -> None:
    plan = Plan(
        code="enterprise",
        name="Enterprise",
        monthly_price_paise=None,
        currency="INR",
        included_seats=None,
        is_custom_pricing=True,
    )

    assert plan.monthly_price_paise is None
    assert plan.included_seats is None
    assert plan.is_custom_pricing is True


def test_plan_model_defaults_are_configured() -> None:
    assert Plan.__table__.c.id.default is not None
    assert Plan.__table__.c.is_custom_pricing.default is not None
    assert Plan.__table__.c.is_active.default is not None


def test_plan_entitlement_model_fields() -> None:
    plan_id = __import__("uuid").uuid4()

    entitlement = PlanEntitlement(
        plan_id=plan_id,
        key="max_seats",
        value_type="INTEGER",
        value=5,
        description="Maximum included seats.",
    )

    assert entitlement.id is None
    assert entitlement.plan_id == plan_id
    assert entitlement.key == "max_seats"
    assert entitlement.value_type == "INTEGER"
    assert entitlement.value == 5


def test_plan_entitlement_has_unique_plan_key_constraint() -> None:
    constraints = {
        constraint.name
        for constraint in PlanEntitlement.__table__.constraints
    }

    assert "uq_plan_entitlements_plan_key" in constraints


def test_subscription_supports_optional_plan_relationship() -> None:
    subscription = Subscription(
        organization_id=__import__("uuid").uuid4(),
        plan_code="legacy-plan",
        plan_id=None,
    )

    assert subscription.plan_code == "legacy-plan"
    assert subscription.plan_id is None
    assert subscription.plan is None