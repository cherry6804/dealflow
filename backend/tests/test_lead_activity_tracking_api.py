"""Regression tests for automatic Lead status and owner activity tracking."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.models.activity import Activity
from app.db.models.lead import Lead
from tests.test_leads_lifecycle_api import (
    TestingSessionLocal,
    create_authorized_user,
    create_contact,
    create_lead,
    create_membership,
    create_user,
    make_test_client,
    patch_lead,
)


def get_lead_activities(
    db: Session,
    *,
    organization_id: UUID,
    lead_id: UUID,
) -> list[Activity]:
    """Retrieve activities for a lead within its organization."""
    statement = select(Activity).where(
        Activity.organization_id == organization_id,
        Activity.lead_id == lead_id,
    )

    return list(db.scalars(statement).all())


def test_status_change_creates_activity_with_actor_and_details() -> None:
    db = TestingSessionLocal()

    try:
        user, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        contact = create_contact(
            db,
            organization=organization,
        )
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEW,
            next_action="Call customer",
        )

        db.commit()

        with make_test_client(user=user) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={"status": Lead.STATUS_CONTACTED},
            )

        assert response.status_code == 200, response.text

        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 1

        activity = activities[0]
        assert activity.activity_type == Activity.TYPE_STATUS_CHANGE
        assert activity.actor_id == user.id
        assert activity.details == {
            "old_status": Lead.STATUS_NEW,
            "new_status": Lead.STATUS_CONTACTED,
        }
        assert activity.occurred_at is not None

    finally:
        db.rollback()
        db.close()


def test_owner_assignment_creates_activity() -> None:
    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        owner = create_user(db)

        create_membership(
            db,
            user=owner,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
        )

        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={"owner_user_id": str(owner.id)},
            )

        assert response.status_code == 200, response.text

        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 1

        activity = activities[0]
        assert activity.activity_type == Activity.TYPE_OWNER_CHANGE
        assert activity.actor_id == actor.id
        assert activity.details == {
            "old_owner_user_id": None,
            "new_owner_user_id": str(owner.id),
        }

    finally:
        db.rollback()
        db.close()


def test_owner_reassignment_records_old_and_new_owner() -> None:
    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        old_owner = create_user(db)
        new_owner = create_user(db)

        create_membership(
            db,
            user=old_owner,
            organization=organization,
        )
        create_membership(
            db,
            user=new_owner,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            owner_user_id=old_owner.id,
        )

        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={"owner_user_id": str(new_owner.id)},
            )

        assert response.status_code == 200, response.text

        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 1

        activity = activities[0]
        assert activity.activity_type == Activity.TYPE_OWNER_CHANGE
        assert activity.actor_id == actor.id
        assert activity.details == {
            "old_owner_user_id": str(old_owner.id),
            "new_owner_user_id": str(new_owner.id),
        }

    finally:
        db.rollback()
        db.close()


def test_owner_removal_creates_activity() -> None:
    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        owner = create_user(db)

        create_membership(
            db,
            user=owner,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            owner_user_id=owner.id,
        )

        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={"owner_user_id": None},
            )

        assert response.status_code == 200, response.text

        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 1

        activity = activities[0]
        assert activity.activity_type == Activity.TYPE_OWNER_CHANGE
        assert activity.actor_id == actor.id
        assert activity.details == {
            "old_owner_user_id": str(owner.id),
            "new_owner_user_id": None,
        }

    finally:
        db.rollback()
        db.close()


def test_unchanged_status_and_owner_create_no_activities() -> None:
    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        owner = create_user(db)

        create_membership(
            db,
            user=owner,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_CONTACTED,
            owner_user_id=owner.id,
        )

        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_CONTACTED,
                    "owner_user_id": str(owner.id),
                },
            )

        assert response.status_code == 200, response.text

        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert activities == []

    finally:
        db.rollback()
        db.close()


def test_combined_status_and_owner_change_creates_two_activities() -> None:
    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        owner = create_user(db)

        create_membership(
            db,
            user=owner,
            organization=organization,
        )

        contact = create_contact(
            db,
            organization=organization,
        )
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEW,
            next_action="Call customer",
        )

        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "status": Lead.STATUS_CONTACTED,
                    "owner_user_id": str(owner.id),
                },
            )

        assert response.status_code == 200, response.text

        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 2

        by_type = {
            activity.activity_type: activity
            for activity in activities
        }

        assert set(by_type) == {
            Activity.TYPE_STATUS_CHANGE,
            Activity.TYPE_OWNER_CHANGE,
        }

        status_activity = by_type[Activity.TYPE_STATUS_CHANGE]
        assert status_activity.actor_id == actor.id
        assert status_activity.details == {
            "old_status": Lead.STATUS_NEW,
            "new_status": Lead.STATUS_CONTACTED,
        }

        owner_activity = by_type[Activity.TYPE_OWNER_CHANGE]
        assert owner_activity.actor_id == actor.id
        assert owner_activity.details == {
            "old_owner_user_id": None,
            "new_owner_user_id": str(owner.id),
        }

    finally:
        db.rollback()
        db.close()


def test_activity_insert_failure_does_not_commit_lead_change() -> None:
    db = TestingSessionLocal()

    def fail_activity_insert(mapper, connection, target) -> None:
        raise RuntimeError("Simulated activity insert failure.")

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        contact = create_contact(
            db,
            organization=organization,
        )
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            status=Lead.STATUS_NEW,
            next_action="Call customer",
        )
        lead_id = lead.id
        organization_id = organization.id

        db.commit()

        event.listen(
            Activity,
            "before_insert",
            fail_activity_insert,
        )

        try:
            with make_test_client(user=actor) as client:
                with pytest.raises(
                    RuntimeError,
                    match="Simulated activity insert failure",
                ):
                    patch_lead(
                        client,
                        organization=organization,
                        lead_id=lead_id,
                        payload={"status": Lead.STATUS_CONTACTED},
                    )
        finally:
            event.remove(
                Activity,
                "before_insert",
                fail_activity_insert,
            )

        db.expire_all()

        persisted_lead = db.scalar(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.organization_id == organization_id,
            )
        )

        assert persisted_lead is not None
        assert persisted_lead.status == Lead.STATUS_NEW

        activities = get_lead_activities(
            db,
            organization_id=organization_id,
            lead_id=lead_id,
        )

        assert activities == []

    finally:
        db.rollback()
        db.close()

def test_next_action_change_creates_activity_with_actor_and_details() -> None:
    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        contact = create_contact(db, organization=organization)
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
        )
        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={"next_action": "Arrange property visit"},
            )

        assert response.status_code == 200, response.text
        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 1
        activity = activities[0]
        assert activity.activity_type == Activity.TYPE_OTHER
        assert activity.title == "Lead next action changed"
        assert activity.actor_id == actor.id
        assert activity.details == {
            "field": "next_action",
            "old_next_action": "Call customer",
            "new_next_action": "Arrange property visit",
        }

    finally:
        db.rollback()
        db.close()


def test_next_action_schedule_change_creates_activity() -> None:
    from datetime import datetime, timedelta, timezone

    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        contact = create_contact(db, organization=organization)
        old_time = datetime.now(timezone.utc) + timedelta(days=1)
        new_time = datetime.now(timezone.utc) + timedelta(days=3)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
            next_action_at=old_time,
        )
        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={"next_action_at": new_time.isoformat()},
            )

        assert response.status_code == 200, response.text
        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 1
        activity = activities[0]
        assert activity.activity_type == Activity.TYPE_OTHER
        assert activity.title == "Lead follow-up schedule changed"
        assert activity.actor_id == actor.id
        assert activity.details["field"] == "next_action_at"
        assert activity.details["old_next_action_at"] is not None
        assert activity.details["new_next_action_at"] is not None

    finally:
        db.rollback()
        db.close()


def test_clearing_next_action_creates_activity() -> None:
    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        contact = create_contact(db, organization=organization)
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
        )
        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={"next_action": None},
            )

        assert response.status_code == 200, response.text
        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert len(activities) == 1
        assert activities[0].details == {
            "field": "next_action",
            "old_next_action": "Call customer",
            "new_next_action": None,
        }

    finally:
        db.rollback()
        db.close()


def test_unchanged_next_action_fields_create_no_activities() -> None:
    from datetime import datetime, timedelta, timezone

    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        contact = create_contact(db, organization=organization)
        scheduled_at = datetime.now(timezone.utc) + timedelta(days=2)

        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
            next_action_at=scheduled_at,
        )
        db.commit()

        with make_test_client(user=actor) as client:
            response = patch_lead(
                client,
                organization=organization,
                lead_id=lead.id,
                payload={
                    "next_action": "Call customer",
                    "next_action_at": scheduled_at.isoformat(),
                },
            )

        assert response.status_code == 200, response.text
        db.expire_all()

        activities = get_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )
        assert activities == []

    finally:
        db.rollback()
        db.close()


def test_next_action_activity_insert_failure_rolls_back_lead_update() -> None:
    def fail_activity_insert(mapper, connection, target) -> None:
        if target.title == "Lead next action changed":
            raise RuntimeError("Simulated next-action activity insert failure.")

    db = TestingSessionLocal()

    try:
        actor, organization, _, _, _ = create_authorized_user(
            db,
            permission_key="leads.update",
        )
        contact = create_contact(db, organization=organization)
        lead = create_lead(
            db,
            organization=organization,
            contact=contact,
            next_action="Call customer",
        )
        lead_id = lead.id
        organization_id = organization.id
        db.commit()

        from sqlalchemy import event

        event.listen(Activity, "before_insert", fail_activity_insert)

        try:
            with make_test_client(user=actor) as client:
                with pytest.raises(
                    RuntimeError,
                    match="Simulated next-action activity insert failure",
                ):
                    patch_lead(
                        client,
                        organization=organization,
                        lead_id=lead_id,
                        payload={"next_action": "Arrange property visit"},
                    )
        finally:
            event.remove(Activity, "before_insert", fail_activity_insert)

        db.expire_all()

        persisted_lead = db.scalar(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.organization_id == organization_id,
            )
        )

        assert persisted_lead is not None
        assert persisted_lead.next_action == "Call customer"

        activities = get_lead_activities(
            db,
            organization_id=organization_id,
            lead_id=lead_id,
        )
        assert activities == []

    finally:
        db.rollback()
        db.close()