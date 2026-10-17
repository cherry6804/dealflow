
"""Tests for the tenant-scoped business document upload API."""

from __future__ import annotations
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.documents import service as document_service
import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.api.documents import router as documents_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.document import Document
from app.db.session import SessionLocal, get_db_session
from app.documents import service as document_service
from app.storage.local import LocalObjectStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from tests.test_contacts_api import (
    create_authorized_user,
    create_membership,
    create_organization,
    create_user,
)


PERMISSION_KEY = "documents.upload"
UPLOAD_URL = "/api/v1/documents/uploads"
PDF_CONTENT = b"%PDF-1.4\nSample document content\n%%EOF\n"


def configure_document_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    max_size: int = 1024 * 1024,
) -> None:
    """Use isolated local storage and a predictable upload-size limit."""
    monkeypatch.setattr(
        document_service,
        "get_settings",
        lambda: SimpleNamespace(
            upload_max_file_size_bytes=max_size,
            object_storage_backend="local",
            object_storage_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(
        document_service,
        "get_object_storage",
        lambda: LocalObjectStorage(tmp_path),
    )


def get_test_db_session():
    """Yield a test database session and roll back remaining changes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def create_document_test_app(user) -> FastAPI:
    """Create a test app with document upload and test authentication."""
    app = FastAPI()
    app.include_router(documents_router)

    app.dependency_overrides[get_db_session] = get_test_db_session
    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )
    return app


def post_document_upload(
    client: TestClient,
    filename: str = "agreement.pdf",
    content: bytes = PDF_CONTENT,
    content_type: str = "application/pdf",
    *,
    data: dict[str, str] | None = None,
):
    """Submit a document and its metadata as multipart form data."""
    form_data = {
        "document_type": "Agreement",
        "category": "AGREEMENT",
        "access_classification": "INTERNAL",
    }
    if data:
        form_data.update(data)

    return client.post(
        UPLOAD_URL,
        files={"file": (filename, content, content_type)},
        data=form_data,
    )


def test_upload_pdf_persists_metadata_and_private_object(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Persist document metadata and the file under its tenant."""
    configure_document_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        user_id = user.id
        organization_id = organization.id

        with TestClient(create_document_test_app(user)) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_document_upload(
                client,
                data={"display_name": "Signed Agreement"},
            )

        assert response.status_code == 201, response.text
        payload = response.json()

        document_id = UUID(payload["id"])
        assert payload["organization_id"] == str(organization_id)
        assert payload["original_filename"] == "agreement.pdf"
        assert payload["display_name"] == "Signed Agreement"
        assert payload["category"] == "AGREEMENT"
        assert payload["document_type"] == "Agreement"
        assert payload["content_type"] == "application/pdf"
        assert payload["file_size_bytes"] == len(PDF_CONTENT)
        assert payload["checksum_sha256"] == hashlib.sha256(
            PDF_CONTENT
        ).hexdigest()
        assert payload["access_classification"] == "INTERNAL"
        assert payload["status"] == "AVAILABLE"
        assert payload["uploaded_by_user_id"] == str(user_id)
        assert payload["uploaded_at"]
        assert payload["created_at"]
        assert payload["updated_at"]

        # Internal storage paths must not be exposed by the API.
        assert "storage_key" not in payload
        assert "storage_backend" not in payload

    with SessionLocal() as verify_db:
        document = verify_db.get(Document, document_id)

        assert document is not None
        assert document.organization_id == organization_id
        assert document.uploaded_by_user_id == user_id
        assert document.status == "AVAILABLE"
        assert document.storage_backend == "local"
        assert document.storage_key is not None

        stored_path = tmp_path.joinpath(
            *document.storage_key.split("/")
        )
        assert stored_path.read_bytes() == PDF_CONTENT
        assert document.storage_key.startswith(
            f"{organization_id}/"
        )


def test_upload_rejects_unsupported_extension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject unsupported file types without storing an object."""
    configure_document_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with TestClient(create_document_test_app(user)) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = post_document_upload(
                client,
                filename="malware.exe",
                content=b"not an executable we accept",
                content_type="application/octet-stream",
            )

    assert response.status_code == 422
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("empty.pdf", b""),
        ("invalid.pdf", b"this is not a PDF"),
        ("invalid.png", b"not a PNG image"),
        ("invalid.docx", b"not a DOCX archive"),
    ],
)
def test_upload_rejects_invalid_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    filename: str,
    content: bytes,
) -> None:
    """Reject empty or invalid file content."""
    configure_document_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with TestClient(create_document_test_app(user)) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = post_document_upload(
                client,
                filename=filename,
                content=content,
                content_type="application/octet-stream",
            )

    assert response.status_code == 422
    assert list(tmp_path.rglob("*")) == []


def test_upload_rejects_file_over_configured_size_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Return 413 when the upload exceeds the configured limit."""
    configure_document_storage(monkeypatch, tmp_path, max_size=8)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with TestClient(create_document_test_app(user)) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = post_document_upload(
                client,
                content=PDF_CONTENT,
            )

    assert response.status_code == 413
    assert list(tmp_path.rglob("*")) == []


def test_upload_requires_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject an upload when no organization is selected."""
    configure_document_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, _organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )

        with TestClient(create_document_test_app(user)) as client:
            response = post_document_upload(client)

    assert response.status_code == 400
    assert list(tmp_path.rglob("*")) == []


def test_upload_requires_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject users whose organization membership lacks permission."""
    configure_document_storage(monkeypatch, tmp_path)

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

        with TestClient(create_document_test_app(user)) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_document_upload(client)

    assert response.status_code == 403
    assert list(tmp_path.rglob("*")) == []


def test_upload_uses_selected_verified_organization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Save the document under the verified tenant, not another tenant."""
    configure_document_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        organization_id = organization.id
        other_organization = create_organization(setup_db)
        other_organization_id = other_organization.id
        setup_db.commit()

        with TestClient(create_document_test_app(user)) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_document_upload(client)

        assert response.status_code == 201, response.text
        document_id = UUID(response.json()["id"])

    with SessionLocal() as verify_db:
        document = verify_db.get(Document, document_id)

        assert document is not None
        assert document.organization_id == organization_id
        assert document.organization_id != other_organization_id
        assert document.storage_key.startswith(
            f"{organization_id}/"
        )


def test_upload_cleans_up_object_when_database_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Remove the stored object when metadata persistence fails."""
    configure_document_storage(monkeypatch, tmp_path)

    with SessionLocal() as setup_db:
        user, organization = create_authorized_user(
            setup_db,
            permission_key=PERMISSION_KEY,
        )
        user_id = user.id
        organization_id = organization.id

    app = create_document_test_app(user)

    # Keep the authenticated ORM user attached to a live session.
    auth_db = SessionLocal()
    authenticated_user = auth_db.get(type(user), user_id)
    assert authenticated_user is not None

    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=authenticated_user)
    )

    def override_failing_database():
        db = SessionLocal()

        def failing_commit() -> None:
            raise SQLAlchemyError(
                "Simulated document metadata commit failure"
            )

        db.commit = failing_commit

        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_failing_database

    try:
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_id)}
            )
            response = post_document_upload(client)

        assert response.status_code == 500
        remaining_files = [
            path for path in tmp_path.rglob("*") if path.is_file()
        ]
        assert remaining_files == []
    finally:
        auth_db.close()


def make_office_archive(entries: dict[str, bytes]) -> BytesIO:
    """Build a small in-memory Office-style ZIP archive."""
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    output.seek(0)
    return output


def test_office_archive_rejects_too_many_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject archives that exceed the entry-count limit."""
    monkeypatch.setattr(
        document_service, "MAX_OFFICE_ARCHIVE_ENTRIES", 1
    )
    source = make_office_archive({"one.xml": b"1", "two.xml": b"2"})

    with pytest.raises(
        document_service.DocumentUploadValidationError,
        match="too many archive entries",
    ):
        document_service._validate_content(source, ".docx")


def test_office_archive_rejects_oversized_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an individual entry larger than the configured limit."""
    monkeypatch.setattr(
        document_service, "MAX_OFFICE_ENTRY_BYTES", 10
    )
    source = make_office_archive({"large.xml": b"x" * 11})

    with pytest.raises(
        document_service.DocumentUploadValidationError,
        match="entry exceeds the size limit",
    ):
        document_service._validate_content(source, ".docx")


def test_office_archive_rejects_excessive_total_uncompressed_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject archives whose combined uncompressed size is too large."""
    monkeypatch.setattr(
        document_service, "MAX_OFFICE_UNCOMPRESSED_BYTES", 15
    )
    source = make_office_archive(
        {"first.xml": b"12345678", "second.xml": b"abcdefgh"}
    )

    with pytest.raises(
        document_service.DocumentUploadValidationError,
        match="expands beyond the permitted size",
    ):
        document_service._validate_content(source, ".docx")


def test_office_archive_rejects_excessive_compression_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject entries whose compression ratio exceeds the configured limit."""
    monkeypatch.setattr(
        document_service, "MAX_OFFICE_COMPRESSION_RATIO", 2
    )
    source = make_office_archive({"repetitive.xml": b"A" * 1_000})

    with pytest.raises(
        document_service.DocumentUploadValidationError,
        match="compression ratio exceeds the limit",
    ):
        document_service._validate_content(source, ".docx")
