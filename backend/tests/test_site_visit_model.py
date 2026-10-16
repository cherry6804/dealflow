import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import configure_mappers

from app.db.models import SiteVisit


def test_site_visit_model_has_expected_table_name() -> None:
    assert SiteVisit.__tablename__ == "site_visits"


def test_site_visit_model_has_expected_columns() -> None:
    assert set(SiteVisit.__table__.columns.keys()) == {
        "id",
        "organization_id",
        "property_id",
        "lead_id",
        "customer_profile_id",
        "owner_user_id",
        "scheduled_at",
        "ends_at",
        "status",
        "outcome",
        "notes",
        "feedback",
        "created_at",
        "updated_at",
    }


def test_site_visit_model_uses_uuid_primary_key() -> None:
    column = SiteVisit.__table__.c.id

    assert column.primary_key is True
    assert column.default is not None
    assert column.type.python_type is uuid.UUID

def test_site_visit_model_is_tenant_scoped() -> None:
    column = SiteVisit.__table__.c.organization_id

    assert column.nullable is False

    direct_organization_foreign_keys = [
        foreign_key
        for foreign_key in column.foreign_keys
        if foreign_key.target_fullname == "organizations.id"
        and foreign_key.constraint.name is None
    ]

    assert len(direct_organization_foreign_keys) == 1



def test_site_visit_model_has_tenant_safe_property_constraint() -> None:
    constraints = SiteVisit.__table__.foreign_key_constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "fk_site_visits_property_tenant"
    )

    assert [column.name for column in constraint.columns] == [
        "property_id",
        "organization_id",
    ]
    assert [
        element.target_fullname for element in constraint.elements
    ] == [
        "properties.id",
        "properties.organization_id",
    ]
    assert constraint.ondelete == "RESTRICT"


def test_site_visit_model_has_tenant_safe_lead_constraint() -> None:
    constraints = SiteVisit.__table__.foreign_key_constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "fk_site_visits_lead_tenant"
    )

    assert [column.name for column in constraint.columns] == [
        "lead_id",
        "organization_id",
    ]
    assert [
        element.target_fullname for element in constraint.elements
    ] == [
        "leads.id",
        "leads.organization_id",
    ]
    assert constraint.ondelete == "RESTRICT"


def test_site_visit_model_has_tenant_safe_customer_profile_constraint() -> None:
    constraints = SiteVisit.__table__.foreign_key_constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "fk_site_visits_customer_profile_tenant"
    )

    assert [column.name for column in constraint.columns] == [
        "customer_profile_id",
        "organization_id",
    ]
    assert [
        element.target_fullname for element in constraint.elements
    ] == [
        "customer_profiles.id",
        "customer_profiles.organization_id",
    ]
    assert constraint.ondelete == "RESTRICT"


def test_site_visit_model_has_tenant_safe_owner_constraint() -> None:
    constraints = SiteVisit.__table__.foreign_key_constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "fk_site_visits_owner_membership_tenant"
    )

    assert [column.name for column in constraint.columns] == [
        "owner_user_id",
        "organization_id",
    ]
    assert [
        element.target_fullname for element in constraint.elements
    ] == [
        "organization_memberships.user_id",
        "organization_memberships.organization_id",
    ]
    assert constraint.ondelete == "RESTRICT"


def test_site_visit_model_defines_supported_statuses() -> None:
    assert SiteVisit.STATUS_VALUES == (
        "SCHEDULED",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )


def test_site_visit_model_defines_supported_outcomes() -> None:
    assert SiteVisit.OUTCOME_VALUES == (
        "INTERESTED",
        "NOT_INTERESTED",
        "NEGOTIATION",
        "FOLLOW_UP_REQUIRED",
        "OTHER",
    )


def test_site_visit_model_has_query_indexes() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in SiteVisit.__table__.indexes
    }

    assert indexes["ix_site_visits_org_scheduled_at"] == (
        "organization_id",
        "scheduled_at",
    )

    assert indexes["ix_site_visits_org_property_scheduled"] == (
        "organization_id",
        "property_id",
        "scheduled_at",
    )

    assert indexes["ix_site_visits_org_owner_status_scheduled"] == (
        "organization_id",
        "owner_user_id",
        "status",
        "scheduled_at",
    )


def test_site_visit_model_timestamps_and_optional_fields() -> None:
    columns = SiteVisit.__table__.columns

    assert columns.property_id.nullable is False
    assert columns.lead_id.nullable is True
    assert columns.customer_profile_id.nullable is True
    assert columns.owner_user_id.nullable is False

    assert columns.scheduled_at.nullable is False
    assert columns.ends_at.nullable is True
    assert columns.outcome.nullable is True
    assert columns.notes.nullable is True

    assert columns.created_at.nullable is False
    assert columns.created_at.server_default is not None

    assert columns.updated_at.nullable is False
    assert columns.updated_at.server_default is not None
    assert columns.updated_at.onupdate is not None


def test_site_visit_model_has_expected_check_constraints() -> None:
    constraints = {
        constraint.name: constraint
        for constraint in SiteVisit.__table__.constraints
    }

    assert "ck_site_visits_status" in constraints
    assert "ck_site_visits_outcome" in constraints
    assert "ck_site_visits_time_range" in constraints
    assert "ck_site_visits_customer_reference" in constraints


def test_site_visit_model_has_composite_unique_constraint() -> None:
    constraints = {
        constraint.name: constraint
        for constraint in SiteVisit.__table__.constraints
    }

    constraint = constraints["uq_site_visits_id_organization"]

    assert tuple(column.name for column in constraint.columns) == (
        "id",
        "organization_id",
    )


def test_site_visit_model_can_be_constructed() -> None:
    visit_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    property_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    scheduled_at = datetime(
        2026, 10, 20, 10, 0, tzinfo=timezone.utc
    )
    ends_at = datetime(
        2026, 10, 20, 11, 0, tzinfo=timezone.utc
    )

    visit = SiteVisit(
        id=visit_id,
        organization_id=organization_id,
        property_id=property_id,
        lead_id=lead_id,
        owner_user_id=owner_user_id,
        scheduled_at=scheduled_at,
        ends_at=ends_at,
        status=SiteVisit.STATUS_SCHEDULED,
        outcome=None,
        notes="Confirm the customer's property requirements.",
    )

    assert visit.id == visit_id
    assert visit.organization_id == organization_id
    assert visit.property_id == property_id
    assert visit.lead_id == lead_id
    assert visit.customer_profile_id is None
    assert visit.owner_user_id == owner_user_id
    assert visit.scheduled_at == scheduled_at
    assert visit.ends_at == ends_at
    assert visit.status == SiteVisit.STATUS_SCHEDULED
    assert visit.outcome is None
    assert visit.notes == "Confirm the customer's property requirements."


def test_site_visit_model_can_be_constructed_for_customer_profile() -> None:
    customer_profile_id = uuid.uuid4()

    visit = SiteVisit(
        organization_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        customer_profile_id=customer_profile_id,
        owner_user_id=uuid.uuid4(),
        scheduled_at=datetime(
            2026, 10, 20, 10, 0, tzinfo=timezone.utc
        ),
        status=SiteVisit.STATUS_SCHEDULED,
    )

    assert visit.customer_profile_id == customer_profile_id
    assert visit.lead_id is None


def test_site_visit_model_mappers_configure_successfully() -> None:
    configure_mappers()