"""API tests for Customer Requirement history creation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from sqlalchemy import select

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_history import (
    CustomerRequirementHistory,
)
from app.requirements.history_service import (
    create_customer_requirement_history,
)
from tests.test_customer_requirements_api import (
    TestingSessionLocal,
    add_tenant_header,
    create_authorized_user,
    make_test_client,
)


def test_create_customer_requirement_creates_initial_history() -> None:
    """Creating a requirement creates its initial immutable history version."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 201

        payload = response.json()
        requirement_id = UUID(payload["id"])

        verification_db = TestingSessionLocal()

        try:
            requirement = verification_db.scalar(
                select(CustomerRequirement).where(
                    CustomerRequirement.id == requirement_id,
                    CustomerRequirement.organization_id == organization.id,
                )
            )

            assert requirement is not None

            histories = list(
                verification_db.scalars(
                    select(CustomerRequirementHistory)
                    .where(
                        CustomerRequirementHistory.customer_requirement_id
                        == requirement_id,
                        CustomerRequirementHistory.organization_id
                        == organization.id,
                    )
                    .order_by(CustomerRequirementHistory.version.asc())
                ).all()
            )

            assert len(histories) == 1

            history = histories[0]

            assert history.customer_requirement_id == requirement.id
            assert history.organization_id == organization.id
            assert history.version == 1
            assert history.actor_id == user.id
            assert history.change_type == "REQUIREMENT_CREATED"
            assert history.occurred_at is not None

            assert history.snapshot["requirement"] == {
                "id": str(requirement.id),
                "organization_id": str(organization.id),
                "status": requirement.status,
                "is_active": requirement.is_active,
                "budget_min": None,
                "budget_max": None,
                "budget_currency": None,
                "lead_id": None,
                "customer_profile_id": None,
                "created_at": requirement.created_at.isoformat(),
                "updated_at": requirement.updated_at.isoformat(),
            }

            assert history.snapshot["locations"] == []
            assert history.snapshot["property_preferences"] == []
            assert history.snapshot["possession_parking_preference"] is None

        finally:
            verification_db.close()


def test_create_customer_requirement_history_is_tenant_scoped() -> None:
    """Initial history belongs only to the requirement's tenant."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 201

        requirement_id = UUID(response.json()["id"])

        other_organization = organization.__class__(
            name=f"Other Organization-{requirement_id}",
            is_active=True,
        )

        db.add(other_organization)
        db.commit()
        db.refresh(other_organization)

        verification_db = TestingSessionLocal()

        try:
            tenant_history = list(
                verification_db.scalars(
                    select(CustomerRequirementHistory)
                    .where(
                        CustomerRequirementHistory.customer_requirement_id
                        == requirement_id,
                        CustomerRequirementHistory.organization_id
                        == organization.id,
                    )
                ).all()
            )

            cross_tenant_history = list(
                verification_db.scalars(
                    select(CustomerRequirementHistory)
                    .where(
                        CustomerRequirementHistory.customer_requirement_id
                        == requirement_id,
                        CustomerRequirementHistory.organization_id
                        == other_organization.id,
                    )
                ).all()
            )

            assert len(tenant_history) == 1
            assert cross_tenant_history == []

        finally:
            verification_db.close()


def test_customer_requirement_history_concurrent_version_allocation() -> None:
    """Concurrent history writes receive unique sequential versions."""

    permission_key = "requirements.create"

    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=permission_key,
        )

        with make_test_client(user=user) as client:
            add_tenant_header(client, organization)

            response = client.post(
                "/api/v1/customer-requirements",
                json={},
            )

        assert response.status_code == 201

        requirement_id = UUID(response.json()["id"])

    def create_history_concurrently() -> int:
        worker_db = TestingSessionLocal()

        try:
            requirement = worker_db.scalar(
                select(CustomerRequirement).where(
                    CustomerRequirement.id == requirement_id,
                    CustomerRequirement.organization_id == organization.id,
                )
            )

            assert requirement is not None

            create_customer_requirement_history(
                worker_db,
                requirement=requirement,
                organization_id=organization.id,
                actor_id=user.id,
                change_type="REQUIREMENT_UPDATED",
            )

            history = worker_db.scalar(
                select(CustomerRequirementHistory)
                .where(
                    CustomerRequirementHistory.customer_requirement_id
                    == requirement_id,
                    CustomerRequirementHistory.organization_id
                    == organization.id,
                )
                .order_by(CustomerRequirementHistory.version.desc())
            )

            assert history is not None

            version = history.version

            worker_db.commit()

            return version

        except Exception:
            worker_db.rollback()
            raise

        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(create_history_concurrently),
            executor.submit(create_history_concurrently),
        ]

        versions = sorted(future.result() for future in futures)

    assert versions == [2, 3]

    with TestingSessionLocal() as verification_db:
        histories = list(
            verification_db.scalars(
                select(CustomerRequirementHistory)
                .where(
                    CustomerRequirementHistory.customer_requirement_id
                    == requirement_id,
                    CustomerRequirementHistory.organization_id
                    == organization.id,
                )
                .order_by(CustomerRequirementHistory.version.asc())
            ).all()
        )

        assert [history.version for history in histories] == [1, 2, 3]
        assert len(
            {
                history.version
                for history in histories
            }
        ) == 3