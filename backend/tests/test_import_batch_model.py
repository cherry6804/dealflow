
import uuid

from app.db.models.import_batch import ImportBatch


def test_import_batch_has_expected_table_name() -> None:
    assert ImportBatch.__tablename__ == "import_batches"


def test_import_batch_has_expected_columns() -> None:
    assert set(ImportBatch.__table__.columns.keys()) == {
        "id",
        "organization_id",
        "source_filename",
        "source_format",
        "content_type",
        "file_size_bytes",
        "status",
        "total_rows",
        "processed_rows",
        "successful_rows",
        "failed_rows",
        "skipped_rows",
        "error_summary",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    }


def test_import_batch_uses_uuid_primary_key() -> None:
    column = ImportBatch.__table__.c.id

    assert column.primary_key is True
    assert column.default is not None


def test_import_batch_is_tenant_scoped() -> None:
    column = ImportBatch.__table__.c.organization_id

    assert column.nullable is False
    assert column.index is True

    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.target_fullname == "organizations.id"
    assert foreign_key.ondelete == "CASCADE"


def test_import_batch_required_and_optional_metadata() -> None:
    columns = ImportBatch.__table__.columns

    assert columns.source_filename.nullable is False
    assert columns.source_format.nullable is False
    assert columns.content_type.nullable is True
    assert columns.file_size_bytes.nullable is True
    assert columns.error_summary.nullable is True
    assert columns.started_at.nullable is True
    assert columns.completed_at.nullable is True


def test_import_batch_status_default() -> None:
    column = ImportBatch.__table__.c.status

    assert column.nullable is False
    assert column.default.arg == "pending"
    assert column.server_default is not None


def test_import_batch_counters_default_to_zero() -> None:
    for name in (
        "total_rows",
        "processed_rows",
        "successful_rows",
        "failed_rows",
        "skipped_rows",
    ):
        column = ImportBatch.__table__.c[name]

        assert column.nullable is False
        assert column.default.arg == 0
        assert column.server_default is not None


def test_import_batch_timestamps() -> None:
    columns = ImportBatch.__table__.columns

    assert columns.created_at.nullable is False
    assert columns.created_at.server_default is not None

    assert columns.updated_at.nullable is False
    assert columns.updated_at.server_default is not None
    assert columns.updated_at.onupdate is not None


def test_import_batch_can_be_constructed() -> None:
    organization_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    batch = ImportBatch(
        id=batch_id,
        organization_id=organization_id,
        source_filename="contacts.csv",
        source_format="csv",
        content_type="text/csv",
        file_size_bytes=1024,
        status="pending",
    )

    assert batch.id == batch_id
    assert batch.organization_id == organization_id
    assert batch.source_filename == "contacts.csv"
    assert batch.source_format == "csv"
    assert batch.content_type == "text/csv"
    assert batch.file_size_bytes == 1024
    assert batch.status == "pending"
