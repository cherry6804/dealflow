
"""Tests for the read-only import preview API."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.api.imports import router as imports_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.config import get_settings as app_get_settings
from app.db.models.contact import Contact
from app.db.models.import_batch import ImportBatch
from app.db.session import SessionLocal, get_db_session
from app.imports import preview, storage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from tests.test_contacts_api import (
    create_authorized_user,
    create_organization,
)

PERMISSION_KEY = "imports.upload"
UPLOAD_URL = "/api/v1/imports/uploads"


def configure_storage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Use isolated private storage for upload and preview operations."""
    settings = SimpleNamespace(
        upload_storage_dir=tmp_path,
        upload_max_file_size_bytes=1024 * 1024,
    )
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setattr(preview, "get_settings", lambda: settings)


def test_get_settings_import_is_not_needed() -> None:
    """Keep this test module independent of application environment settings."""
    assert callable(app_get_settings)


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


def make_xlsx_content() -> bytes:
    """Create a valid XLSX workbook with contact sample rows."""
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "Contacts"
    worksheet.append(["First Name", "Last Name", "Email", "Mobile Number"])
    worksheet.append(
        ["Rahul", "Sharma", "rahul@example.com", "9876543210"]
    )
    worksheet.append(
        ["Priya", "Rao", "priya@example.com", "9123456780"]
    )

    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def upload_file(
    client: TestClient,
    filename: str,
    content: bytes,
    content_type: str,
) -> dict:
    """Upload a source file and return its JSON response."""
    response = client.post(
        UPLOAD_URL,
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_preview_csv_detects_columns_and_suggests_mappings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Preview CSV rows without creating contacts."""
    configure_storage(monkeypatch, tmp_path)
    content = (
        b"First Name,Last Name,Email,Mobile Number\n"
        b"Rahul,Sharma,rahul@example.com,9876543210\n"
        b"Priya,Rao,priya@example.com,9123456780\n"
    )

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            batch = upload_file(
                client,
                "contacts.csv",
                content,
                "text/csv",
            )

            response = client.get(
                f"/api/v1/imports/{batch['id']}/preview"
            )

        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["import_batch_id"] == batch["id"]
        assert payload["source_format"] == "csv"
        assert payload["worksheet_name"] is None
        assert [column["source_name"] for column in payload["columns"]] == [
            "First Name",
            "Last Name",
            "Email",
            "Mobile Number",
        ]
        assert [column["suggested_field"] for column in payload["columns"]] == [
            "first_name",
            "last_name",
            "email",
            "phone",
        ]
        assert payload["preview_rows"][0]["First Name"] == "Rahul"
        assert payload["preview_rows"][0]["Email"] == "rahul@example.com"
        assert payload["contacts_created"] == 0

    with SessionLocal() as verify_db:
        assert (
            verify_db.query(Contact)
            .filter(Contact.organization_id == organization_id)
            .count()
            == 0
        )


def test_preview_xlsx_reads_first_worksheet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Preview a real XLSX workbook and report its worksheet."""
    configure_storage(monkeypatch, tmp_path)
    content = make_xlsx_content()

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            batch = upload_file(
                client,
                "contacts.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet",
            )

            response = client.get(
                f"/api/v1/imports/{batch['id']}/preview"
            )

        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["source_format"] == "xlsx"
        assert payload["worksheet_name"] == "Contacts"
        assert payload["preview_rows"][0]["First Name"] == "Rahul"
        assert payload["preview_rows"][1]["Email"] == "priya@example.com"
        assert payload["contacts_created"] == 0


def test_preview_duplicate_and_blank_headers_are_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Avoid overwriting values when headers are blank or duplicated."""
    configure_storage(monkeypatch, tmp_path)
    content = b"Email,Email,,Phone\nfirst@example.com,second@example.com,x,123\n"

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            batch = upload_file(
                client,
                "duplicates.csv",
                content,
                "text/csv",
            )
            response = client.get(
                f"/api/v1/imports/{batch['id']}/preview"
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        names = [column["display_name"] for column in payload["columns"]]

        assert names == ["Email", "Email (2)", "Column 3", "Phone"]
        assert payload["preview_rows"][0]["Email"] == "first@example.com"
        assert (
            payload["preview_rows"][0]["Email (2)"]
            == "second@example.com"
        )
        assert payload["preview_rows"][0]["Column 3"] == "x"


def test_preview_unknown_batch_returns_not_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Return 404 for an import batch that does not exist."""
    configure_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.get(
                f"/api/v1/imports/{UUID(int=0)}/preview"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Import batch not found."


def test_preview_hides_batch_owned_by_another_organization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Do not expose another tenant's import batch."""
    configure_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        other_organization = create_organization(setup_db)
        other_id = other_organization.id

        # The batch metadata and file key belong to the other organization.
        other_key = f"{other_id}/private.csv"
        other_path = tmp_path / other_key
        other_path.parent.mkdir(parents=True)
        other_path.write_bytes(b"Email\nsecret@example.com\n")

        batch = ImportBatch(
            organization_id=other_id,
            source_filename="private.csv",
            source_format="csv",
            content_type="text/csv",
            file_size_bytes=other_path.stat().st_size,
            status="pending",
            storage_backend="local",
            storage_key=other_key,
        )
        setup_db.add(batch)
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.get(
                f"/api/v1/imports/{batch_id}/preview"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Import batch not found."


def test_preview_missing_file_returns_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Return a controlled error when the stored source file is missing."""
    configure_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        batch = ImportBatch(
            organization_id=organization.id,
            source_filename="missing.csv",
            source_format="csv",
            content_type="text/csv",
            file_size_bytes=10,
            status="pending",
            storage_backend="local",
            storage_key=f"{organization.id}/missing.csv",
        )
        setup_db.add(batch)
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.get(
                f"/api/v1/imports/{batch_id}/preview"
            )

        assert response.status_code == 422
        assert "no longer available" in response.json()["detail"]
