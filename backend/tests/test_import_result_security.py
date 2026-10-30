"""Security regression tests for persisted import results and CSV exports."""

from __future__ import annotations

import json

from app.db.models.user import User
from app.db.session import SessionLocal
from tests.test_contacts_api import create_authorized_user
from tests.test_import_processing_api import (
    PERMISSION_KEY,
    create_stored_batch,
    make_client,
)


def create_result_test_data(
    *,
    storage_key: str,
    error_summary: dict,
) -> tuple[str, str, str]:
    """Persist a batch and return its IDs without retaining detached ORM objects."""
    with SessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_key=PERMISSION_KEY,
        )
        user_id = str(user.id)
        organization_id = str(organization.id)

        batch = create_stored_batch(
            db,
            organization_id=organization.id,
            storage_key=f"{organization.id}/{storage_key}",
        )
        batch.status = "completed_with_errors"
        batch.error_summary = json.dumps(error_summary)
        batch_id = str(batch.id)

        db.commit()

    return user_id, organization_id, batch_id


def request_as_user(
    *,
    user_id: str,
    organization_id: str,
    path: str,
):
    """Make an API request using a user loaded in an active database session."""
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = organization_id
            return client.get(path)


def test_import_errors_csv_escapes_formula_like_messages() -> None:
    """Escape formula-like error text before spreadsheet users open the CSV."""
    user_id, organization_id, batch_id = create_result_test_data(
        storage_key="formula-test.csv",
        error_summary={
            "errors": [
                {
                    "row_number": 2,
                    "field": "email",
                    "code": "invalid_format",
                    "message": "=1+1",
                },
                {
                    "row_number": 3,
                    "field": "first_name",
                    "code": "required",
                    "message": "  @SUM(A1:A2)",
                },
            ],
            "error_limit": 100,
            "errors_truncated": False,
        },
    )

    response = request_as_user(
        user_id=user_id,
        organization_id=organization_id,
        path=f"/api/v1/imports/{batch_id}/errors.csv",
    )

    assert response.status_code == 200, response.text
    assert "'=1+1" in response.text
    assert "'  @SUM(A1:A2)" in response.text


def test_import_result_rejects_malformed_persisted_error_entries() -> None:
    """Return a controlled server error for invalid stored error entries."""
    user_id, organization_id, batch_id = create_result_test_data(
        storage_key="malformed-result.csv",
        error_summary={
            "errors": [
                {
                    "row_number": "not-a-row-number",
                    "field": "email",
                    "code": "invalid_format",
                    "message": "Invalid email",
                }
            ],
            "error_limit": 100,
            "errors_truncated": False,
        },
    )

    response = request_as_user(
        user_id=user_id,
        organization_id=organization_id,
        path=f"/api/v1/imports/{batch_id}/result",
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "The stored import result could not be read."
    )


def test_import_errors_csv_rejects_malformed_persisted_error_entries() -> None:
    """Do not generate a CSV from invalid persisted error entries."""
    user_id, organization_id, batch_id = create_result_test_data(
        storage_key="malformed-csv.csv",
        error_summary={
            "errors": [{"row_number": 2}],
            "error_limit": 100,
            "errors_truncated": False,
        },
    )

    response = request_as_user(
        user_id=user_id,
        organization_id=organization_id,
        path=f"/api/v1/imports/{batch_id}/errors.csv",
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "The stored import result could not be read."
    )