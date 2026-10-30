"""Tests for private import-source storage and validation."""

import asyncio
import io
import uuid
import zipfile
from pathlib import Path

import pytest
from app.config import Settings
from app.imports import storage
from starlette.datastructures import UploadFile as StarletteUploadFile


def make_upload(
    filename: str,
    content: bytes,
    *,
    content_type: str = "application/octet-stream",
) -> StarletteUploadFile:
    """Build an upload object with an in-memory source."""
    return StarletteUploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers={"content-type": content_type},
    )


def make_xlsx_bytes() -> bytes:
    """Build a minimal ZIP-shaped XLSX fixture for structural validation."""
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"></Types>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"></workbook>',
        )

    return buffer.getvalue()


def configure_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    max_size: int = 1024,
) -> Path:
    """Configure isolated temporary private storage for a test."""
    root = tmp_path / "private_uploads"

    settings = Settings(
        _env_file="",
        upload_storage_dir=root,
        upload_max_file_size_bytes=max_size,
    )

    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    return root


def test_sanitize_source_filename_removes_path_components() -> None:
    assert (
        storage.sanitize_source_filename(
            r"C:\Users\example\contacts.csv"
        )
        == "contacts.csv"
    )


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "../contacts.csv.exe",
        "contacts.exe",
        "contacts.xls",
        ".csv",
    ],
)
def test_sanitize_source_filename_rejects_invalid_names(
    filename: str,
) -> None:
    with pytest.raises(storage.UploadValidationError):
        storage.sanitize_source_filename(filename)


def test_store_valid_csv(monkeypatch, tmp_path) -> None:
    root = configure_storage(monkeypatch, tmp_path)
    organization_id = uuid.uuid4()
    content = b"first_name,email\r\nAsha,asha@example.com\r\n"

    result = asyncio.run(
        storage.store_upload(
            make_upload(
                "contacts.csv",
                content,
                content_type="text/csv",
            ),
            organization_id=organization_id,
        )
    )

    assert result.source_filename == "contacts.csv"
    assert result.source_format == "csv"
    assert result.content_type == "text/csv"
    assert result.file_size_bytes == len(content)
    assert result.storage_backend == "local"
    assert result.storage_key.startswith(f"{organization_id}/")
    assert result.storage_key.endswith(".csv")
    assert result.path.is_file()
    assert result.path.read_bytes() == content

    # The returned storage key is relative, not an absolute filesystem path.
    assert not Path(result.storage_key).is_absolute()
    assert str(root) not in result.storage_key


def test_store_valid_xlsx(monkeypatch, tmp_path) -> None:
    configure_storage(monkeypatch, tmp_path)
    content = make_xlsx_bytes()

    result = asyncio.run(
        storage.store_upload(
            make_upload("contacts.xlsx", content),
            organization_id=uuid.uuid4(),
        )
    )

    assert result.source_format == "xlsx"
    assert result.file_size_bytes == len(content)
    assert result.path.read_bytes() == content


def test_store_rejects_empty_file(monkeypatch, tmp_path) -> None:
    root = configure_storage(monkeypatch, tmp_path)

    with pytest.raises(storage.UploadValidationError):
        asyncio.run(
            storage.store_upload(
                make_upload("empty.csv", b""),
                organization_id=uuid.uuid4(),
            )
        )

    assert list(root.rglob("*")) == []


def test_store_rejects_invalid_csv_and_cleans_up(
    monkeypatch,
    tmp_path,
) -> None:
    root = configure_storage(monkeypatch, tmp_path)

    with pytest.raises(storage.UploadValidationError):
        asyncio.run(
            storage.store_upload(
                make_upload("contacts.csv", b"\xff\xfe\x00\x00"),
                organization_id=uuid.uuid4(),
            )
        )

    assert list(root.rglob("*")) == []


def test_store_rejects_invalid_xlsx_and_cleans_up(
    monkeypatch,
    tmp_path,
) -> None:
    root = configure_storage(monkeypatch, tmp_path)

    with pytest.raises(storage.UploadValidationError):
        asyncio.run(
            storage.store_upload(
                make_upload("contacts.xlsx", b"not a workbook"),
                organization_id=uuid.uuid4(),
            )
        )

    assert list(root.rglob("*")) == []


def test_store_rejects_file_over_size_limit_and_cleans_up(
    monkeypatch,
    tmp_path,
) -> None:
    root = configure_storage(
        monkeypatch,
        tmp_path,
        max_size=16,
    )

    with pytest.raises(storage.UploadTooLargeError):
        asyncio.run(
            storage.store_upload(
                make_upload("contacts.csv", b"a,b\n" + b"x" * 20),
                organization_id=uuid.uuid4(),
            )
        )

    assert list(root.rglob("*")) == []


def test_delete_stored_upload_rejects_path_traversal(
    monkeypatch,
    tmp_path,
) -> None:
    root = configure_storage(monkeypatch, tmp_path)
    outside_file = tmp_path / "outside.csv"
    outside_file.write_text("private", encoding="utf-8")

    with pytest.raises(ValueError):
        storage.delete_stored_upload("../outside.csv")

    assert outside_file.read_text(encoding="utf-8") == "private"
    assert not root.exists()


def test_delete_stored_upload_removes_file(
    monkeypatch,
    tmp_path,
) -> None:
    root = configure_storage(monkeypatch, tmp_path)
    organization_id = uuid.uuid4()
    storage_key = f"{organization_id}/test.csv"
    target = root / storage_key
    target.parent.mkdir(parents=True)
    target.write_bytes(b"first_name\nAsha\n")

    storage.delete_stored_upload(storage_key)

    assert not target.exists()
