"""Tests for the read-only import row validation API."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.imports import router as imports_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.contact import Contact
from app.db.models.import_batch import ImportBatch
from app.db.session import SessionLocal, get_db_session

from tests.test_contacts_api import (
    create_authorized_user,
    create_organization,
)

PERMISSION_KEY = "imports.upload"


def get_test_db_session():
    """Yield a database session and roll back uncommitted test changes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def make_client(user) -> TestClient:
    """Create an API client with the existing imports router."""
    app = FastAPI()
    app.include_router(imports_router)
    app.dependency_overrides[get_db_session] = get_test_db_session
    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )
    return TestClient(app)


def create_stored_batch(
    db,
    *,
    organization_id,
    storage_key: str,
    filename: str = "contacts.csv",
) -> ImportBatch:
    """Create import metadata for a source file already in test storage."""
    batch = ImportBatch(
        organization_id=organization_id,
        source_filename=filename,
        source_format="csv",
        content_type="text/csv",
        file_size_bytes=0,
        status="pending",
        storage_backend="local",
        storage_key=storage_key,
    )
    db.add(batch)
    db.flush()
    return batch


def test_validation_reports_valid_and_invalid_rows_without_creating_contacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Validate all CSV data rows without persisting contacts."""
    from types import SimpleNamespace

    from app.imports import preview, storage

    settings = SimpleNamespace(
        upload_storage_dir=tmp_path,
        upload_max_file_size_bytes=1024 * 1024,
    )
    monkeypatch.setattr(preview, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/validation.csv"
        source_path = tmp_path / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name,Last Name,Email,Phone\n"
            "Rahul,Sharma,rahul@example.com,9876543210\n"
            ",Rao,invalid-email,abc\n"
            "Priya,Rao,,\n",
            encoding="utf-8",
        )

        batch = create_stored_batch(
            setup_db,
            organization_id=organization_id,
            storage_key=storage_key,
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            response = client.get(
                f"/api/v1/imports/{batch_id}/validation"
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["import_batch_id"] == str(batch_id)
        assert payload["source_format"] == "csv"
        assert payload["total_rows"] == 3
        assert payload["valid_rows"] == 2
        assert payload["invalid_rows"] == 1
        assert payload["contacts_created"] == 0
        assert {
            (error["row_number"], error["field"], error["code"])
            for error in payload["errors"]
        } == {
            (3, "first_name", "required"),
            (3, "email", "invalid_format"),
            (3, "phone", "invalid_format"),
        }


        with SessionLocal() as verify_db:
            assert (
                verify_db.query(Contact)
                .filter(Contact.organization_id == organization_id)
                .count()
                == 0
            )

    persisted_batch = verify_db.get(ImportBatch, batch_id)
    assert persisted_batch is not None
    assert persisted_batch.status == "pending"
    assert persisted_batch.total_rows == 0
    assert persisted_batch.processed_rows == 0
    assert persisted_batch.successful_rows == 0
    assert persisted_batch.failed_rows == 0
    assert persisted_batch.skipped_rows == 0
    assert persisted_batch.error_summary is None
    assert persisted_batch.started_at is None
    assert persisted_batch.completed_at is None



def test_validation_unknown_batch_returns_not_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Return 404 for an unknown import batch."""
    from types import SimpleNamespace

    from app.imports import preview, storage

    settings = SimpleNamespace(
        upload_storage_dir=tmp_path,
        upload_max_file_size_bytes=1024 * 1024,
    )
    monkeypatch.setattr(preview, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.get(
                f"/api/v1/imports/{UUID(int=0)}/validation"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Import batch not found."


def test_validation_hides_batch_owned_by_another_organization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Do not expose another tenant's import batch."""
    from types import SimpleNamespace

    from app.imports import preview, storage

    settings = SimpleNamespace(
        upload_storage_dir=tmp_path,
        upload_max_file_size_bytes=1024 * 1024,
    )
    monkeypatch.setattr(preview, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        other_organization = create_organization(setup_db)
        other_id = other_organization.id
        storage_key = f"{other_id}/private.csv"
        source_path = tmp_path / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name\nSecret\n",
            encoding="utf-8",
        )

        batch = create_stored_batch(
            setup_db,
            organization_id=other_id,
            storage_key=storage_key,
            filename="private.csv",
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.get(
                f"/api/v1/imports/{batch_id}/validation"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Import batch not found."


def test_validation_missing_source_file_returns_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Return a controlled error when the uploaded source is missing."""
    from types import SimpleNamespace

    from app.imports import preview, storage

    settings = SimpleNamespace(
        upload_storage_dir=tmp_path,
        upload_max_file_size_bytes=1024 * 1024,
    )
    monkeypatch.setattr(preview, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        batch = create_stored_batch(
            setup_db,
            organization_id=organization.id,
            storage_key=f"{organization.id}/missing.csv",
            filename="missing.csv",
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.get(
                f"/api/v1/imports/{batch_id}/validation"
            )

        assert response.status_code == 422
        assert "no longer available" in response.json()["detail"]
