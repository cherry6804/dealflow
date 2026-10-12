import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import configure_mappers

from app.db.models import FollowUp


def test_follow_up_model_has_expected_table_name() -> None:
    assert FollowUp.__tablename__ == "follow_ups"


def test_follow_up_model_has_expected_columns() -> None:
    assert set(FollowUp.__table__.columns.keys()) == {
        "id",
        "organization_id",
        "lead_id",
        "owner_user_id",
        "follow_up_type",
        "title",
        "description",
        "due_at",
        "status",
        "completed_at",
        "completed_by_user_id",
        "created_at",
        "updated_at",
    }


def test_follow_up_model_uses_uuid_primary_key() -> None:
    column = FollowUp.__table__.c.id

    assert column.primary_key is True
    assert column.default is not None
    assert column.type.python_type is uuid.UUID


def test_follow_up_model_is_tenant_scoped() -> None:
    column = FollowUp.__table__.c.organization_id

    assert column.nullable is False

    organization_foreign_keys = [
        foreign_key
        for foreign_key in column.foreign_keys
        if foreign_key.target_fullname == "organizations.id"
    ]

    assert len(organization_foreign_keys) == 1


def test_follow_up_model_has_tenant_safe_lead_constraint() -> None:
    constraints = FollowUp.__table__.foreign_key_constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "fk_follow_ups_lead_tenant"
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
    assert constraint.ondelete == "CASCADE"


def test_follow_up_model_has_tenant_safe_owner_constraint() -> None:
    constraints = FollowUp.__table__.foreign_key_constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "fk_follow_ups_owner_membership_tenant"
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


def test_follow_up_model_has_tenant_safe_completer_constraint() -> None:
    constraints = FollowUp.__table__.foreign_key_constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "fk_follow_ups_completed_by_membership_tenant"
    )

    assert [column.name for column in constraint.columns] == [
        "completed_by_user_id",
        "organization_id",
    ]
    assert [
        element.target_fullname for element in constraint.elements
    ] == [
        "organization_memberships.user_id",
        "organization_memberships.organization_id",
    ]
    assert constraint.ondelete == "RESTRICT"


def test_follow_up_model_defines_supported_statuses() -> None:
    assert FollowUp.STATUS_VALUES == (
        "PENDING",
        "COMPLETED",
        "CANCELLED",
    )


def test_follow_up_model_defines_supported_types() -> None:
    assert FollowUp.TYPE_VALUES == (
        "CALL",
        "EMAIL",
        "MEETING",
        "VISIT",
        "TASK",
        "OTHER",
    )


def test_follow_up_model_has_query_indexes() -> None:
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in FollowUp.__table__.indexes
    }

    assert indexes["ix_follow_ups_org_status_due_at"] == (
        "organization_id",
        "status",
        "due_at",
    )
    assert indexes["ix_follow_ups_org_lead_due_at"] == (
        "organization_id",
        "lead_id",
        "due_at",
    )
    assert indexes["ix_follow_ups_owner_status_due_at"] == (
        "owner_user_id",
        "status",
        "due_at",
    )


def test_follow_up_model_timestamps() -> None:
    columns = FollowUp.__table__.columns

    assert columns.due_at.nullable is False
    assert columns.completed_at.nullable is True

    assert columns.created_at.nullable is False
    assert columns.created_at.server_default is not None

    assert columns.updated_at.nullable is False
    assert columns.updated_at.server_default is not None
    assert columns.updated_at.onupdate is not None


def test_follow_up_model_has_completion_consistency_constraint() -> None:
    constraints = FollowUp.__table__.constraints

    constraint = next(
        item
        for item in constraints
        if item.name == "ck_follow_ups_completion_fields"
    )

    assert constraint is not None


def test_follow_up_model_can_be_constructed() -> None:
    follow_up_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    owner_user_id = uuid.uuid4()
    due_at = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)

    follow_up = FollowUp(
        id=follow_up_id,
        organization_id=organization_id,
        lead_id=lead_id,
        owner_user_id=owner_user_id,
        follow_up_type=FollowUp.TYPE_CALL,
        title="Call customer",
        description="Confirm the property visit.",
        due_at=due_at,
        status=FollowUp.STATUS_PENDING,
    )

    assert follow_up.id == follow_up_id
    assert follow_up.organization_id == organization_id
    assert follow_up.lead_id == lead_id
    assert follow_up.owner_user_id == owner_user_id
    assert follow_up.follow_up_type == FollowUp.TYPE_CALL
    assert follow_up.title == "Call customer"
    assert follow_up.description == "Confirm the property visit."
    assert follow_up.due_at == due_at
    assert follow_up.status == FollowUp.STATUS_PENDING
    assert follow_up.completed_at is None
    assert follow_up.completed_by_user_id is None


def test_follow_up_model_mappers_configure_successfully() -> None:
    configure_mappers()
