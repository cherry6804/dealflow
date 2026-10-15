"""DF-109 tests for immutable match and shortlist history."""

from unittest.mock import patch

from sqlalchemy import select

from app.db.models import (
    Membership,
    MembershipRole,
    Property,
    RequirementMatchRun,
    RequirementMatchRunResult,
    RequirementShortlistEvent,
    Role,
)
from tests.test_customer_requirements_api import (
    TestingSessionLocal,
    add_tenant_header,
    assign_permission_to_role,
    create_authorized_user,
    create_customer_requirement,
    get_or_create_permission,
    make_test_client,
)


BASE_URL = "/api/v1/customer-requirements"


def create_property(db, organization_id):
    """Create a minimal property belonging to the specified tenant."""
    property_record = Property(
        organization_id=organization_id,
        status=Property.STATUS_AVAILABLE,
        transaction_type=Property.TRANSACTION_TYPE_SALE,
        city="Chennai",
        locality="Tambaram",
        property_type="APARTMENT",
        bhk=2,
    )
    db.add(property_record)
    db.commit()
    db.refresh(property_record)
    return property_record


def grant_read_permission(db, user, organization):
    """Grant requirements.read to the user's existing organization role."""
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == organization.id,
        )
    )
    assert membership is not None

    membership_role = db.scalar(
        select(MembershipRole).where(
            MembershipRole.membership_id == membership.id,
        )
    )
    assert membership_role is not None

    role = db.get(Role, membership_role.role_id)
    assert role is not None

    permission = get_or_create_permission(
        db,
        key="requirements.read",
    )
    assign_permission_to_role(
        db,
        role=role,
        permission=permission,
    )
    db.commit()


def test_create_match_run_persists_result_snapshots():
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        property_record = create_property(db, organization.id)

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            response = client.post(
                f"{BASE_URL}/{requirement.id}/match-runs",
            )

        assert response.status_code == 201, response.text
        payload = response.json()

        assert payload["id"]
        assert payload["organization_id"] == str(organization.id)
        assert payload["customer_requirement_id"] == str(requirement.id)
        assert payload["actor_id"] == str(user.id)
        assert payload["total_candidates"] == 1
        assert payload["created_at"]
        assert len(payload["results"]) == 1

        result = payload["results"][0]
        assert result["property_id"] == str(property_record.id)
        assert result["property_snapshot"]["id"] == str(property_record.id)
        assert isinstance(result["criteria_results_snapshot"], list)

        with TestingSessionLocal() as verify_db:
            run = verify_db.scalar(
                select(RequirementMatchRun).where(
                    RequirementMatchRun.id == payload["id"],
                    RequirementMatchRun.organization_id == organization.id,
                )
            )
            saved_results = list(
                verify_db.scalars(
                    select(RequirementMatchRunResult).where(
                        RequirementMatchRunResult.match_run_id == payload["id"],
                        RequirementMatchRunResult.organization_id
                        == organization.id,
                    )
                ).all()
            )

        assert run is not None
        assert len(saved_results) == 1


def test_match_run_history_remains_available_after_requirement_deletion():
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            create_response = client.post(
                f"{BASE_URL}/{requirement.id}/match-runs",
            )

        assert create_response.status_code == 201, create_response.text
        run_id = create_response.json()["id"]

        # History intentionally has no FK to the live requirement.
        with TestingSessionLocal() as delete_db:
            live_requirement = delete_db.get(
                type(requirement),
                requirement.id,
            )
            assert live_requirement is not None
            delete_db.delete(live_requirement)
            delete_db.commit()

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)
            history_response = client.get(
                f"{BASE_URL}/{requirement.id}/match-runs",
            )
            results_response = client.get(
                f"{BASE_URL}/{requirement.id}/match-runs/{run_id}/results",
            )

        assert history_response.status_code == 200, history_response.text
        assert history_response.json()["total"] == 1
        assert history_response.json()["items"][0]["id"] == run_id
        assert results_response.status_code == 200, results_response.text


def test_shortlist_add_and_remove_create_immutable_events():
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.update",
        )
        grant_read_permission(db, user, organization)

        requirement = create_customer_requirement(
            db,
            organization=organization,
        )
        property_record = create_property(db, organization.id)
        shortlist_url = f"{BASE_URL}/{requirement.id}/shortlist"

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            add_response = client.post(
                shortlist_url,
                json={"property_id": str(property_record.id)},
            )
            assert add_response.status_code == 201, add_response.text

            remove_response = client.delete(
                f"{shortlist_url}/{property_record.id}",
            )
            assert remove_response.status_code == 204, remove_response.text

            events_response = client.get(
                f"{BASE_URL}/{requirement.id}/shortlist-events",
            )

        assert events_response.status_code == 200, events_response.text
        payload = events_response.json()
        assert payload["total"] == 2

        events = payload["items"]
        assert [event["event_type"] for event in events] == [
            "ADDED",
            "REMOVED",
        ]
        assert all(event["actor_id"] == str(user.id) for event in events)
        assert all(
            event["property_id"] == str(property_record.id)
            for event in events
        )
        assert all(
            event["property_snapshot"]["id"] == str(property_record.id)
            for event in events
        )

        with TestingSessionLocal() as verify_db:
            persisted_events = list(
                verify_db.scalars(
                    select(RequirementShortlistEvent).where(
                        RequirementShortlistEvent.organization_id
                        == organization.id,
                        RequirementShortlistEvent.customer_requirement_id
                        == requirement.id,
                    )
                ).all()
            )

        assert len(persisted_events) == 2


def test_match_run_creation_rejects_another_tenants_requirement():
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        _, organization_b = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement_b = create_customer_requirement(
            db,
            organization=organization_b,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization_a)
            response = client.post(
                f"{BASE_URL}/{requirement_b.id}/match-runs",
            )

        assert response.status_code == 404
        assert response.json()["detail"] == (
            "Active customer requirement not found."
        )


def test_match_run_failure_rolls_back_persisted_run():
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key="requirements.read",
        )
        requirement = create_customer_requirement(
            db,
            organization=organization,
        )

        # Ensure at least one result exists, so the injected failure happens
        # after the run row has been flushed.
        create_property(db, organization.id)

        from app.requirements import match_history_service

        original_json_value = match_history_service._json_value
        snapshot_calls = 0

        def fail_on_result_snapshot(value):
            nonlocal snapshot_calls
            snapshot_calls += 1

            # Call 1 serializes the criteria before the run is inserted.
            # Call 2 serializes the property after db.flush() has flushed
            # the run into the current transaction.
            if snapshot_calls == 2:
                raise RuntimeError("Simulated result snapshot failure")

            return original_json_value(value)

        with make_test_client(
            user=user,
            raise_server_exceptions=False,
        ) as client:
            add_tenant_header(client, organization)

            with patch(
                "app.requirements.match_history_service._json_value",
                side_effect=fail_on_result_snapshot,
            ):
                response = client.post(
                    f"{BASE_URL}/{requirement.id}/match-runs",
                )

        assert response.status_code == 500
        assert snapshot_calls == 2

        with TestingSessionLocal() as verify_db:
            runs = list(
                verify_db.scalars(
                    select(RequirementMatchRun).where(
                        RequirementMatchRun.organization_id == organization.id,
                        RequirementMatchRun.customer_requirement_id
                        == requirement.id,
                    )
                ).all()
            )
            results = list(
                verify_db.scalars(
                    select(RequirementMatchRunResult).where(
                        RequirementMatchRunResult.organization_id
                        == organization.id,
                    )
                ).all()
            )

        assert runs == []
        assert results == []