"""Tests for contact import processing without lead activation."""

from __future__ import annotations

from io import BytesIO
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select

from app.api.imports import router as imports_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.contact import Contact
from app.db.models.import_batch import ImportBatch
from app.db.models.lead import Lead
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
    """Create an API client with the imports router."""
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
    """Create metadata for a source file in test storage."""
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


@pytest.fixture
def import_storage(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Configure import storage to use a temporary directory."""
    from types import SimpleNamespace

    from app.imports import preview, storage

    settings = SimpleNamespace(
        upload_storage_dir=tmp_path,
        upload_max_file_size_bytes=1024 * 1024,
    )
    monkeypatch.setattr(preview, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    return tmp_path


def test_processing_creates_contacts_without_creating_leads(
    import_storage,
) -> None:
    """Create valid contacts only and complete the batch successfully."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/processing.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name,Last Name,Email,Phone\n"
            "Rahul,Sharma,rahul@example.com,9876543210\n"
            "Priya,Rao,priya@example.com,9123456780\n",
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
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["import_batch_id"] == str(batch_id)
        assert payload["status"] == "completed"
        assert payload["total_rows"] == 2
        assert payload["processed_rows"] == 2
        assert payload["successful_rows"] == 2
        assert payload["failed_rows"] == 0
        assert payload["skipped_rows"] == 0
        assert payload["contacts_created"] == 2
        assert payload["errors"] == []
        assert payload["errors_truncated"] is False

        with SessionLocal() as verify_db:
            contacts = list(
                verify_db.scalars(
                    select(Contact).where(
                        Contact.organization_id == organization_id
                    )
                ).all()
            )
            assert len(contacts) == 2
            assert {contact.first_name for contact in contacts} == {
                "Rahul",
                "Priya",
            }
            assert all(contact.is_active for contact in contacts)

            contacts_by_name = {
                contact.first_name: contact for contact in contacts
            }

            rahul = contacts_by_name["Rahul"]
            assert rahul.import_batch_id == batch_id
            assert rahul.source_row_number == 2
            assert rahul.imported_at is not None
            assert rahul.imported_at.tzinfo is not None

            priya = contacts_by_name["Priya"]
            assert priya.import_batch_id == batch_id
            assert priya.source_row_number == 3
            assert priya.imported_at is not None
            assert priya.imported_at.tzinfo is not None
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Lead)
                    .where(Lead.organization_id == organization_id)
                )
                == 0
            )

            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "completed"
            assert persisted_batch.total_rows == 2
            assert persisted_batch.processed_rows == 2
            assert persisted_batch.successful_rows == 2
            assert persisted_batch.failed_rows == 0
            assert persisted_batch.skipped_rows == 0
            assert persisted_batch.started_at is not None
            assert persisted_batch.completed_at is not None


def test_processing_imports_valid_rows_and_reports_invalid_rows(
    import_storage,
) -> None:
    """Import valid rows while recording errors for invalid rows."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/mixed.csv"
        source_path = import_storage / storage_key
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
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "completed_with_errors"
        assert payload["total_rows"] == 3
        assert payload["processed_rows"] == 3
        assert payload["successful_rows"] == 2
        assert payload["failed_rows"] == 1
        assert payload["skipped_rows"] == 1
        assert payload["contacts_created"] == 2
        assert {
            (error["row_number"], error["field"], error["code"])
            for error in payload["errors"]
        } == {
            (3, "first_name", "required"),
            (3, "email", "invalid_format"),
            (3, "phone", "invalid_format"),
        }

        with SessionLocal() as verify_db:
            contacts = list(
                verify_db.scalars(
                    select(Contact).where(
                        Contact.organization_id == organization_id
                    )
                ).all()
            )
            assert len(contacts) == 2
            assert {contact.first_name for contact in contacts} == {
                "Rahul",
                "Priya",
            }
            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "completed_with_errors"
            assert persisted_batch.error_summary is not None


def test_processing_unknown_batch_returns_not_found(
    import_storage,
) -> None:
    """Return 404 for an unknown batch ID."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.post(
                f"/api/v1/imports/{UUID(int=0)}/process"
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Import batch not found."


def test_processing_hides_another_organizations_batch(
    import_storage,
) -> None:
    """Do not process a batch belonging to another tenant."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        other_organization = create_organization(setup_db)
        other_id = other_organization.id
        storage_key = f"{other_id}/private.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name\nPrivate Contact\n",
            encoding="utf-8",
        )
        batch = create_stored_batch(
            setup_db,
            organization_id=other_id,
            storage_key=storage_key,
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 404

        with SessionLocal() as verify_db:
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Contact)
                    .where(Contact.organization_id == other_id)
                )
                == 0
            )
            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "pending"


def test_processing_completed_batch_is_rejected_without_duplicates(
    import_storage,
) -> None:
    """Reject repeat processing without creating duplicate contacts."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/repeat.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name,Email\n"
            "Rahul,rahul@example.com\n",
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
            first_response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )
            second_response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert first_response.status_code == 200, first_response.text
        assert second_response.status_code == 409
        assert second_response.json()["detail"] == (
            "Only pending import batches can be processed."
        )

        with SessionLocal() as verify_db:
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Contact)
                    .where(Contact.organization_id == organization_id)
                )
                == 1
            )


def test_processing_missing_source_returns_controlled_error(
    import_storage,
) -> None:
    """Return 422 if the stored source file is missing."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        batch = create_stored_batch(
            setup_db,
            organization_id=organization.id,
            storage_key=f"{organization.id}/missing.csv",
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 422
        assert "no longer available" in response.json()["detail"]

        with SessionLocal() as verify_db:
            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "pending"
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Contact)
                    .where(Contact.organization_id == organization.id)
                )
                == 0
            )

def test_processing_invalid_column_mapping_returns_422(
    import_storage,
) -> None:
    """Return 422 when the CSV has no first-name column."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/invalid-mapping.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "Last Name,Email\n"
            "Sharma,rahul@example.com\n",
            encoding="utf-8",
        )
        batch = create_stored_batch(
            setup_db,
            organization_id=organization_id,
            storage_key=storage_key,
            filename="invalid-mapping.csv",
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 422, response.text

        with SessionLocal() as verify_db:
            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "pending"
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Contact)
                    .where(
                        Contact.organization_id == organization_id
                    )
                )
                == 0
            )

def test_processing_malformed_csv_returns_422(
    import_storage,
) -> None:
    """Return 422 when CSV data contains malformed quoting."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/malformed.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            'First Name,Last Name,Email\n'
            'Rahul,Sharma,"rahul@example.com\n',
            encoding="utf-8",
        )
        batch = create_stored_batch(
            setup_db,
            organization_id=organization_id,
            storage_key=storage_key,
            filename="malformed.csv",
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 422, response.text
        assert "malformed" in response.json()["detail"].lower()

        with SessionLocal() as verify_db:
            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "pending"
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Contact)
                    .where(
                        Contact.organization_id == organization_id
                    )
                )
                == 0
            )

def test_processing_xlsx_creates_contacts_without_creating_leads(
    import_storage,
) -> None:
    """Process a real XLSX workbook and create contacts only."""
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "Contacts"
    worksheet.append(["First Name", "Last Name", "Email", "Phone"])
    worksheet.append(
        ["Rahul", "Sharma", "rahul@example.com", "9876543210"]
    )
    worksheet.append(
        ["Priya", "Rao", "priya@example.com", "9123456780"]
    )

    output = BytesIO()
    workbook.save(output)
    workbook.close()

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/processing.xlsx"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(output.getvalue())

        batch = create_stored_batch(
            setup_db,
            organization_id=organization_id,
            storage_key=storage_key,
            filename="processing.xlsx",
        )
        batch.source_format = "xlsx"
        batch.content_type = (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["source_format"] == "xlsx"
        assert payload["worksheet_name"] == "Contacts"
        assert payload["total_rows"] == 2
        assert payload["successful_rows"] == 2
        assert payload["contacts_created"] == 2

        with SessionLocal() as verify_db:
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Contact)
                    .where(
                        Contact.organization_id == organization_id
                    )
                )
                == 2
            )
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Lead)
                    .where(Lead.organization_id == organization_id)
                )
                == 0
            )

def test_processing_database_failure_rolls_back_all_contacts(
    import_storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Roll back earlier contacts if a later contact creation fails."""
    from sqlalchemy.exc import SQLAlchemyError

    from app.imports import processing_service

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/database-failure.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name,Last Name,Email,Phone\n"
            "Rahul,Sharma,rahul@example.com,9876543210\n"
            "Priya,Rao,priya@example.com,9123456780\n",
            encoding="utf-8",
        )
        batch = create_stored_batch(
            setup_db,
            organization_id=organization_id,
            storage_key=storage_key,
        )
        setup_db.commit()
        batch_id = batch.id

        original_create_contact = processing_service.create_contact
        call_count = 0

        def fail_on_second_contact(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise SQLAlchemyError("Simulated database failure")
            return original_create_contact(*args, **kwargs)

        monkeypatch.setattr(
            processing_service,
            "create_contact",
            fail_on_second_contact,
        )

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert response.status_code == 500, response.text
        assert call_count == 2

        with SessionLocal() as verify_db:
            assert (
                verify_db.scalar(
                    select(func.count())
                    .select_from(Contact)
                    .where(
                        Contact.organization_id == organization_id
                    )
                )
                == 0
            )
            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "pending"

        # A retry after rollback should process the batch successfully.
        monkeypatch.setattr(
            processing_service,
            "create_contact",
            original_create_contact,
        )

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            retry_response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )

        assert retry_response.status_code == 200, retry_response.text
        assert retry_response.json()["status"] == "completed"
        assert retry_response.json()["contacts_created"] == 2

        with SessionLocal() as verify_db:
            contacts_created = verify_db.scalar(
                select(func.count())
                .select_from(Contact)
                .where(
                    Contact.organization_id == organization_id,
                    Contact.import_batch_id == batch_id,
                )
            )
            assert contacts_created == 2

            persisted_batch = verify_db.get(ImportBatch, batch_id)
            assert persisted_batch is not None
            assert persisted_batch.status == "completed"


def test_import_result_returns_persisted_summary_and_errors(
    import_storage,
) -> None:
    """Retrieve persisted counts and row-level errors after processing."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/result-summary.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name,Last Name,Email,Phone\n"
            "Rahul,Sharma,rahul@example.com,9876543210\n"
            ",Rao,invalid-email,abc\n",
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
            process_response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )
            assert process_response.status_code == 200, process_response.text

            response = client.get(
                f"/api/v1/imports/{batch_id}/result"
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["import_batch_id"] == str(batch_id)
        assert payload["source_filename"] == "contacts.csv"
        assert payload["source_format"] == "csv"
        assert payload["status"] == "completed_with_errors"
        assert payload["total_rows"] == 2
        assert payload["processed_rows"] == 2
        assert payload["successful_rows"] == 1
        assert payload["failed_rows"] == 1
        assert payload["skipped_rows"] == 1
        assert payload["contacts_created"] == 1
        assert payload["errors_truncated"] is False
        assert payload["error_limit"] == 100
        assert {
            (error["row_number"], error["field"], error["code"])
            for error in payload["errors"]
        } == {
            (3, "first_name", "required"),
            (3, "email", "invalid_format"),
            (3, "phone", "invalid_format"),
        }


def test_import_errors_csv_download_contains_saved_errors(
    import_storage,
) -> None:
    """Download the persisted row-level errors as a CSV file."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        storage_key = f"{organization_id}/errors-download.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name,Email\n"
            "Rahul,rahul@example.com\n"
            ",invalid-email\n",
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
            process_response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )
            assert process_response.status_code == 200, process_response.text

            response = client.get(
                f"/api/v1/imports/{batch_id}/errors.csv"
            )

        assert response.status_code == 200, response.text
        assert "text/csv" in response.headers["content-type"]
        assert "attachment;" in response.headers["content-disposition"]
        assert response.headers["cache-control"] == "no-store"
        assert "row_number,field,code,message" in response.text
        assert "first_name" in response.text
        assert "required" in response.text
        assert "email" in response.text
        assert "invalid_format" in response.text


def test_import_result_and_errors_csv_hide_another_tenants_batch(
    import_storage,
) -> None:
    """Return 404 for result and error downloads across tenant boundaries."""
    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        other_organization = create_organization(setup_db)
        other_id = other_organization.id
        storage_key = f"{other_id}/private-result.csv"
        batch = create_stored_batch(
            setup_db,
            organization_id=other_id,
            storage_key=storage_key,
        )
        batch.status = "completed_with_errors"
        batch.total_rows = 1
        batch.processed_rows = 1
        batch.failed_rows = 1
        batch.skipped_rows = 1
        batch.error_summary = (
            '{"errors":[{"row_number":2,"field":"email",'
            '"code":"invalid_format","message":"Private error"}],'
            '"error_limit":100,"errors_truncated":false}'
        )
        setup_db.commit()
        batch_id = batch.id

        with make_client(user) as client:
            client.headers["X-Organization-ID"] = str(organization.id)
            result_response = client.get(
                f"/api/v1/imports/{batch_id}/result"
            )
            csv_response = client.get(
                f"/api/v1/imports/{batch_id}/errors.csv"
            )

        assert result_response.status_code == 404
        assert result_response.json()["detail"] == "Import batch not found."
        assert csv_response.status_code == 404
        assert csv_response.json()["detail"] == "Import batch not found."

def test_concurrent_processing_of_same_batch_creates_contacts_once(
    import_storage,
) -> None:

    from app.db.models.user import User

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        user_id = user.id
        organization_id = organization.id
        storage_key = f"{organization_id}/concurrent-processing.csv"
        source_path = import_storage / storage_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "First Name,Email\n"
            "Rahul,rahul@example.com\n",
            encoding="utf-8",
        )

        batch = create_stored_batch(
            setup_db,
            organization_id=organization_id,
            storage_key=storage_key,
        )
        setup_db.commit()
        batch_id = batch.id

    barrier = Barrier(2)

    def process_batch_concurrently() -> int:
        with SessionLocal() as user_db:
            worker_user = user_db.get(User, user_id)
            assert worker_user is not None
            user_db.expunge(worker_user)

        with make_client(worker_user) as client:
            client.headers["X-Organization-ID"] = str(organization_id)
            barrier.wait(timeout=10)
            response = client.post(
                f"/api/v1/imports/{batch_id}/process"
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(process_batch_concurrently),
            executor.submit(process_batch_concurrently),
        ]
        statuses = sorted(future.result(timeout=30) for future in futures)

    assert statuses == [200, 409]

    with SessionLocal() as verify_db:
        contacts_created = verify_db.scalar(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.organization_id == organization_id,
                Contact.import_batch_id == batch_id,
            )
        )
        assert contacts_created == 1

        persisted_batch = verify_db.get(ImportBatch, batch_id)
        assert persisted_batch is not None
        assert persisted_batch.status == "completed"
