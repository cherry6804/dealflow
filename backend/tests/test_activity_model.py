import uuid

from sqlalchemy.orm import configure_mappers

from app.db.models import Activity


def test_activity_model_has_expected_table_name() -> None:
    assert Activity.__tablename__ == "activities"


def test_activity_model_has_expected_columns() -> None:
    assert set(Activity.__table__.columns.keys()) == {
        "id",
        "organization_id",
        "lead_id",
        "actor_id",
        "activity_type",
        "title",
        "description",
        "details",
        "occurred_at",
        "created_at",
    }


def test_activity_model_uses_uuid_primary_key() -> None:
    column = Activity.__table__.c.id

    assert column.primary_key is True
    assert column.default is not None
    assert column.type.python_type is uuid.UUID


def test_activity_model_is_tenant_scoped() -> None:
    column = Activity.__table__.c.organization_id

    assert column.nullable is False

    organization_foreign_keys = [
        foreign_key
        for foreign_key in column.foreign_keys
        if foreign_key.target_fullname == "organizations.id"
    ]

    assert len(organization_foreign_keys) == 1


def test_activity_model_has_tenant_safe_lead_constraint() -> None:
    constraints = Activity.__table__.foreign_key_constraints

    lead_constraints = [
        constraint
        for constraint in constraints
        if constraint.name == "fk_activities_lead_tenant"
    ]

    assert len(lead_constraints) == 1

    constraint = lead_constraints[0]

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

    assert constraint.ondelete == "CASCADE"


def test_activity_model_has_tenant_safe_actor_constraint() -> None:
    constraints = Activity.__table__.foreign_key_constraints

    actor_constraints = [
        constraint
        for constraint in constraints
        if constraint.name == "fk_activities_actor_membership_tenant"
    ]

    assert len(actor_constraints) == 1

    constraint = actor_constraints[0]

    assert [column.name for column in constraint.columns] == [
        "actor_id",
        "organization_id",
    ]

    assert [
        element.target_fullname for element in constraint.elements
    ] == [
        "organization_memberships.user_id",
        "organization_memberships.organization_id",
    ]

    assert constraint.ondelete == "RESTRICT"


def test_activity_model_defines_supported_activity_types() -> None:
    assert Activity.TYPE_VALUES == (
        "NOTE",
        "CALL",
        "EMAIL",
        "MEETING",
        "STATUS_CHANGE",
        "OWNER_CHANGE",
        "TASK",
        "OTHER",
    )


def test_activity_model_has_timeline_indexes() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in Activity.__table__.indexes
    }

    assert indexes["ix_activities_org_lead_occurred_at"] == (
        "organization_id",
        "lead_id",
        "occurred_at",
    )

    assert indexes["ix_activities_org_occurred_at"] == (
        "organization_id",
        "occurred_at",
    )

    assert indexes["ix_activities_actor_occurred_at"] == (
        "actor_id",
        "occurred_at",
    )


def test_activity_model_timestamps() -> None:
    columns = Activity.__table__.columns

    assert columns.occurred_at.nullable is False
    assert columns.occurred_at.server_default is not None

    assert columns.created_at.nullable is False
    assert columns.created_at.server_default is not None


def test_activity_model_can_be_constructed() -> None:
    activity_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    activity = Activity(
        id=activity_id,
        organization_id=organization_id,
        lead_id=lead_id,
        actor_id=actor_id,
        activity_type=Activity.TYPE_NOTE,
        title="Initial contact",
        description="Discussed property requirements.",
        details={"channel": "phone"},
    )

    assert activity.id == activity_id
    assert activity.organization_id == organization_id
    assert activity.lead_id == lead_id
    assert activity.actor_id == actor_id
    assert activity.activity_type == Activity.TYPE_NOTE
    assert activity.title == "Initial contact"
    assert activity.description == "Discussed property requirements."
    assert activity.details == {"channel": "phone"}


def test_activity_model_mappers_configure_successfully() -> None:
    configure_mappers()
