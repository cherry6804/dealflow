"""Private file storage and source-file validation for imports."""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from fastapi import UploadFile

from app.config import get_settings

CHUNK_SIZE = 64 * 1024
SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}

# XLSX files are ZIP archives. Bound archive metadata and decompression work
# independently of the uploaded compressed-file size.
MAX_XLSX_ENTRIES = 1_000
MAX_XLSX_TOTAL_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_XLSX_ENTRY_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_XLSX_COMPRESSION_RATIO = 1_000
MAX_XLSX_REQUIRED_COMPONENT_BYTES = 5 * 1024 * 1024

XLSX_REQUIRED_ENTRIES = {
    "[Content_Types].xml",
    "xl/workbook.xml",
}


class UploadValidationError(Exception):
    """Raised when an uploaded source file is invalid."""


class UploadTooLargeError(Exception):
    """Raised when an uploaded source file exceeds its size limit."""


@dataclass(frozen=True)
class StoredUpload:
    """Describe a validated file stored outside public application assets."""

    source_filename: str
    source_format: str
    content_type: str | None
    file_size_bytes: int
    storage_backend: str
    storage_key: str
    path: Path


def sanitize_source_filename(filename: str | None) -> str:
    """Return a safe, bounded display filename without directory components."""
    if not filename:
        raise UploadValidationError("A filename is required.")

    normalized = filename.replace("\\", "/")
    basename = normalized.rsplit("/", maxsplit=1)[-1]
    basename = "".join(
        character
        for character in basename
        if character.isprintable() and character not in {"/", "\\"}
    ).strip()

    if not basename or basename in {".", ".."}:
        raise UploadValidationError("A valid filename is required.")

    if len(basename) > 255:
        raise UploadValidationError(
            "The filename must not exceed 255 characters."
        )

    if Path(basename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UploadValidationError("Only CSV and XLSX files are supported.")

    return basename


def _validate_csv(path: Path) -> None:
    """Validate CSV encoding and basic text structure without importing rows."""
    try:
        with path.open("rb") as source:
            text = io.TextIOWrapper(
                source,
                encoding="utf-8-sig",
                errors="strict",
                newline="",
            )

            first_character = text.read(1)
            if not first_character:
                raise UploadValidationError("The uploaded file is empty.")

            text.seek(0)

            for chunk in iter(lambda: text.read(CHUNK_SIZE), ""):
                if "\x00" in chunk:
                    raise UploadValidationError(
                        "The CSV file contains invalid binary content."
                    )

            text.seek(0)

            try:
                first_row = next(csv.reader(text))
            except StopIteration as exc:
                raise UploadValidationError(
                    "The CSV file does not contain a header row."
                ) from exc

            if not first_row or not any(value.strip() for value in first_row):
                raise UploadValidationError(
                    "The CSV file does not contain a valid header row."
                )

    except UnicodeDecodeError as exc:
        raise UploadValidationError(
            "The CSV file must use UTF-8 encoding."
        ) from exc
    except OSError as exc:
        raise UploadValidationError(
            "The uploaded CSV file could not be validated."
        ) from exc


def _validate_xlsx(path: Path) -> None:
    """Validate bounded XLSX ZIP metadata and required workbook components."""
    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            entries = archive.infolist()

            if len(entries) > MAX_XLSX_ENTRIES:
                raise UploadValidationError(
                    "The XLSX archive contains too many entries."
                )

            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise UploadValidationError(
                    "The XLSX archive contains duplicate entry names."
                )

            if not XLSX_REQUIRED_ENTRIES.issubset(set(names)):
                raise UploadValidationError(
                    "The XLSX file is missing required workbook components."
                )

            total_uncompressed_bytes = 0

            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise UploadValidationError(
                        "Encrypted XLSX archives are not supported."
                    )

                if entry.file_size < 0 or entry.compress_size < 0:
                    raise UploadValidationError(
                        "The XLSX archive contains invalid size metadata."
                    )

                if entry.file_size > MAX_XLSX_ENTRY_UNCOMPRESSED_BYTES:
                    raise UploadValidationError(
                        "An XLSX archive entry exceeds the allowed size."
                    )

                total_uncompressed_bytes += entry.file_size
                if (
                    total_uncompressed_bytes
                    > MAX_XLSX_TOTAL_UNCOMPRESSED_BYTES
                ):
                    raise UploadValidationError(
                        "The XLSX archive exceeds the allowed expanded size."
                    )

                if entry.file_size:
                    if entry.compress_size == 0:
                        raise UploadValidationError(
                            "The XLSX archive contains suspicious compression."
                        )

                    compression_ratio = entry.file_size / entry.compress_size
                    if compression_ratio > MAX_XLSX_COMPRESSION_RATIO:
                        raise UploadValidationError(
                            "The XLSX archive contains suspicious compression."
                        )

            # Read only the small required metadata components. This checks
            # their integrity without decompressing every worksheet or entry.
            for component_name in XLSX_REQUIRED_ENTRIES:
                component = archive.getinfo(component_name)

                if (
                    component.file_size
                    > MAX_XLSX_REQUIRED_COMPONENT_BYTES
                ):
                    raise UploadValidationError(
                        "An XLSX workbook component exceeds the allowed size."
                    )

                with archive.open(component, mode="r") as component_file:
                    content = component_file.read(
                        MAX_XLSX_REQUIRED_COMPONENT_BYTES + 1
                    )

                if len(content) > MAX_XLSX_REQUIRED_COMPONENT_BYTES:
                    raise UploadValidationError(
                        "An XLSX workbook component exceeds the allowed size."
                    )

                if len(content) != component.file_size:
                    raise UploadValidationError(
                        "An XLSX workbook component is incomplete."
                    )

    except BadZipFile as exc:
        raise UploadValidationError(
            "The uploaded XLSX file is not a valid Excel workbook."
        ) from exc
    except (OSError, EOFError, RuntimeError, NotImplementedError) as exc:
        raise UploadValidationError(
            "The uploaded XLSX file could not be validated."
        ) from exc


def validate_source_file(path: Path, filename: str) -> str:
    """Validate file content and return the canonical source format."""
    extension = Path(filename).suffix.lower()

    if extension == ".csv":
        _validate_csv(path)
        return "csv"

    if extension == ".xlsx":
        _validate_xlsx(path)
        return "xlsx"

    raise UploadValidationError("Only CSV and XLSX files are supported.")


def delete_stored_upload(storage_key: str) -> None:
    """Delete a stored upload only when its key resolves inside the storage root."""
    settings = get_settings()
    root = settings.upload_storage_dir.resolve()
    candidate = (root / storage_key).resolve()

    if candidate == root or root not in candidate.parents:
        raise ValueError("The storage key resolves outside the storage root.")

    try:
        candidate.unlink(missing_ok=True)
    finally:
        parent = candidate.parent
        if parent != root:
            try:
                parent.rmdir()
            except OSError:
                pass


async def store_upload(
    upload: UploadFile,
    *,
    organization_id: uuid.UUID,
) -> StoredUpload:
    """Stream, validate, and persist an upload under a server-generated key."""
    settings = get_settings()
    source_filename = sanitize_source_filename(upload.filename)
    extension = Path(source_filename).suffix.lower()
    max_size = settings.upload_max_file_size_bytes

    organization_directory = settings.upload_storage_dir / str(organization_id)
    organization_directory.mkdir(parents=True, exist_ok=True)

    storage_key = f"{organization_id}/{uuid.uuid4().hex}{extension}"
    destination = settings.upload_storage_dir / storage_key
    size = 0

    try:
        with destination.open("xb") as target:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break

                size += len(chunk)
                if size > max_size:
                    raise UploadTooLargeError(
                        f"The file exceeds the {max_size}-byte upload limit."
                    )

                target.write(chunk)

        if size == 0:
            raise UploadValidationError("The uploaded file is empty.")

        source_format = await asyncio.to_thread(
            validate_source_file,
            destination,
            source_filename,
        )

        content_type = upload.content_type
        if content_type:
            content_type = content_type.strip()[:100] or None

        return StoredUpload(
            source_filename=source_filename,
            source_format=source_format,
            content_type=content_type,
            file_size_bytes=size,
            storage_backend="local",
            storage_key=storage_key,
            path=destination,
        )

    except BaseException:
        try:
            delete_stored_upload(storage_key)
        except OSError:
            pass
        raise