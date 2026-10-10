
"""Tests for DealFlow source-file upload API."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from app.api.imports import router as imports_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.import_batch import ImportBatch
from app.db.session import SessionLocal, get_db_session
from app.imports import storage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from tests.test_contacts_api import (
    create_authorized_user,
    create_membership,
    create_organization,
    create_user,
)

PERMISSION_KEY = "imports.upload"
UPLOAD_URL = "/api/v1/imports/uploads"
CSV_CONTENT = b"name,email\nRahul,rahul@example.com\n"


def configure_upload_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    max_size: int = 1024 * 1024,
) -> None:
    """Use an isolated temporary directory for private uploads."""
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: SimpleNamespace(
            upload_storage_dir=tmp_path,
            upload_max_file_size_bytes=max_size,
        ),
    )


def make_xlsx_content() -> bytes:
    """Create a minimal ZIP-based XLSX workbook fixture."""
    output = BytesIO()

    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"></Types>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"></workbook>',
        )

    return output.getvalue()


def get_test_db_session():
    """Yield a database session and roll back uncommitted test changes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def create_upload_test_app(user) -> FastAPI:
    """Create a test app with the upload route and a known test user."""
    app = FastAPI()
    app.include_router(imports_router)

    app.dependency_overrides[get_db_session] = get_test_db_session
    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )

    return app


def make_upload_test_client(user) -> TestClient:
    """Create a client that registers the import route."""
    return TestClient(create_upload_test_app(user))


def post_upload(
    client: TestClient,
    filename: str,
    content: bytes,
    content_type: str = "text/csv",
):
    """Submit one source file to the upload endpoint."""
    return client.post(
        UPLOAD_URL,
        files={"file": (filename, content, content_type)},
    )


def test_upload_csv_persists_file_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Store a CSV and persist its tenant-scoped metadata."""
    configure_upload_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id

        with make_upload_test_client(user) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                "contacts.csv",
                CSV_CONTENT,
            )

        assert response.status_code == 201, response.text
        payload = response.json()

        batch_id = UUID(payload["id"])
        assert payload["organization_id"] == str(organization_id)
        assert payload["source_filename"] == "contacts.csv"
        assert payload["source_format"] == "csv"
        assert payload["content_type"] == "text/csv"
        assert payload["file_size_bytes"] == len(CSV_CONTENT)
        assert payload["status"] == "pending"
        assert payload["total_rows"] == 0
        assert payload["processed_rows"] == 0
        assert payload["successful_rows"] == 0
        assert payload["failed_rows"] == 0
        assert payload["skipped_rows"] == 0
        assert payload["created_at"]
        assert payload["updated_at"]

    with SessionLocal() as verify_db:
        batch = verify_db.get(ImportBatch, batch_id)

        assert batch is not None
        assert batch.organization_id == organization_id
        assert batch.storage_backend == "local"
        assert batch.storage_key is not None
        assert (tmp_path / batch.storage_key).read_bytes() == CSV_CONTENT


def test_upload_xlsx_persists_xlsx_format(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Accept a structurally valid XLSX source."""
    configure_upload_storage(monkeypatch, tmp_path)
    content = make_xlsx_content()

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id

        with make_upload_test_client(user) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                "contacts.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet",
            )

        assert response.status_code == 201, response.text
        assert response.json()["source_format"] == "xlsx"
        assert response.json()["file_size_bytes"] == len(content)


def test_upload_rejects_unsupported_extension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Reject unsupported extensions without retaining uploaded files."""
    configure_upload_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id

        with make_upload_test_client(user) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                "contacts.txt",
                b"hello",
                "text/plain",
            )

    assert response.status_code == 422
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("empty.csv", b""),
        ("invalid.csv", b"\xff\xfe\xfa"),
        ("invalid.xlsx", b"not an Excel workbook"),
    ],
)
def test_upload_rejects_invalid_file_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    filename: str,
    content: bytes,
) -> None:
    """Reject invalid file content and remove partial uploads."""
    configure_upload_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id

        with make_upload_test_client(user) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                filename,
                content,
                "application/octet-stream",
            )

    assert response.status_code == 422
    assert list(tmp_path.rglob("*")) == []


def test_upload_rejects_file_over_configured_size_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Return 413 and remove the partial file when the size limit is exceeded."""
    configure_upload_storage(monkeypatch, tmp_path, max_size=8)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id

        with make_upload_test_client(user) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                "large.csv",
                b"name,email\n" + b"x" * 100,
            )

    assert response.status_code == 413
    assert list(tmp_path.rglob("*")) == []


def test_upload_requires_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Reject requests without an organization-selection header."""
    configure_upload_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, _organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with make_upload_test_client(user) as client:
            response = post_upload(
                client,
                "contacts.csv",
                CSV_CONTENT,
            )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Organization context is required."
    )
    assert list(tmp_path.rglob("*")) == []


def test_upload_requires_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Reject uploads when the tenant membership lacks imports.upload."""
    configure_upload_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user = create_user(setup_db)
        organization = create_organization(setup_db)
        create_membership(
            setup_db,
            user=user,
            organization=organization,
        )
        setup_db.commit()
        organization_id = organization.id

        with make_upload_test_client(user) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                "contacts.csv",
                CSV_CONTENT,
            )

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission denied."
    assert list(tmp_path.rglob("*")) == []


def test_upload_uses_verified_tenant_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Persist the batch under the selected verified organization."""
    configure_upload_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        other_organization = create_organization(setup_db)
        other_organization_id = other_organization.id
        setup_db.commit()

        with make_upload_test_client(user) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                "contacts.csv",
                CSV_CONTENT,
            )

        assert response.status_code == 201, response.text
        batch_id = UUID(response.json()["id"])

    with SessionLocal() as verify_db:
        batch = verify_db.get(ImportBatch, batch_id)

        assert batch is not None
        assert batch.organization_id == organization_id
        assert batch.organization_id != other_organization_id



def test_upload_cleans_up_file_when_database_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Roll back and remove the stored file when commit fails."""
    configure_upload_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        # Capture scalar values before the setup session closes.
        user_id = user.id
        organization_id = organization.id

    app = create_upload_test_app(user)

    # Keep the authenticated ORM user attached to a live session.
    auth_db = SessionLocal()
    authenticated_user = auth_db.get(
        type(user),
        user_id,
    )
    assert authenticated_user is not None

    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=authenticated_user)
    )

    def override_failing_database():
        db = SessionLocal()

        def failing_commit() -> None:
            raise SQLAlchemyError(
                "Simulated database commit failure"
            )

        db.commit = failing_commit

        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = (
        override_failing_database
    )

    try:
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_upload(
                client,
                "contacts.csv",
                CSV_CONTENT,
            )

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "The import upload could not be saved."
        )
        assert list(tmp_path.rglob("*")) == []
    finally:
        auth_db.close()
