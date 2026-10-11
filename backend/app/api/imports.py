"""FastAPI routes for data import operations."""

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.imports.preview import (
    ImportPreviewFileError,
    ImportPreviewNotFoundError,
    get_import_preview,
)
from app.imports.processing_service import (
    ImportProcessingConflictError,
    ImportProcessingFileError,
    ImportProcessingMappingError,
    ImportProcessingNotFoundError,
    process_import_batch,
)
from app.imports.result_service import (
    ImportResultDataError,
    ImportResultNotFoundError,
    get_import_result,
)
from app.imports.schemas import (
    ImportBatchResponse,
    ImportPreviewResponse,
    ImportProcessingResponse,
    ImportResultResponse,
    ImportValidationResponse,
)
from app.imports.service import (
    UploadTooLargeError,
    UploadValidationError,
    upload_import_source,
)
from app.imports.validation_service import (
    ImportValidationFileError,
    ImportValidationMappingError,
    ImportValidationNotFoundError,
    validate_import_source,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(
    prefix="/api/v1/imports",
    tags=["imports"],
)


@router.post(
    "/uploads",
    response_model=ImportBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_import_source_endpoint(
    file: UploadFile = File(...),
    tenant_context: TenantContext = Depends(
        require_permission("imports.upload"),
    ),
    db: Session = Depends(get_db_session),
) -> ImportBatchResponse:
    """Upload and store a source file for the verified tenant."""
    try:
        import_batch = await upload_import_source(
            db=db,
            organization_id=tenant_context.organization_id,
            file=file,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except UploadValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The import upload could not be saved.",
        ) from None
    finally:
        await file.close()

    return ImportBatchResponse.model_validate(import_batch)


@router.get(
    "/{import_batch_id}/preview",
    response_model=ImportPreviewResponse,
    status_code=status.HTTP_200_OK,
)
def preview_import_source_endpoint(
    import_batch_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("imports.upload"),
    ),
    db: Session = Depends(get_db_session),
) -> ImportPreviewResponse:
    """Detect columns and preview source rows for the verified tenant."""
    try:
        preview = get_import_preview(
            db,
            organization_id=tenant_context.organization_id,
            import_batch_id=import_batch_id,
        )
    except ImportPreviewNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found.",
        ) from exc
    except ImportPreviewFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return ImportPreviewResponse.model_validate(preview)


@router.get(
    "/{import_batch_id}/validation",
    response_model=ImportValidationResponse,
    status_code=status.HTTP_200_OK,
)
def validate_import_source_endpoint(
    import_batch_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("imports.upload"),
    ),
    db: Session = Depends(get_db_session),
) -> ImportValidationResponse:
    """Validate rows without creating contacts or changing batch state."""
    try:
        result = validate_import_source(
            db,
            organization_id=tenant_context.organization_id,
            import_batch_id=import_batch_id,
        )
    except ImportValidationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found.",
        ) from exc
    except (
        ImportValidationFileError,
        ImportValidationMappingError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return ImportValidationResponse.model_validate(result)


@router.post(
    "/{import_batch_id}/process",
    response_model=ImportProcessingResponse,
    status_code=status.HTTP_200_OK,
)
def process_import_source_endpoint(
    import_batch_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("imports.upload"),
    ),
    db: Session = Depends(get_db_session),
) -> ImportProcessingResponse:
    """Create contacts from valid rows without activating lead workflows."""
    try:
        result = process_import_batch(
            db,
            organization_id=tenant_context.organization_id,
            import_batch_id=import_batch_id,
        )
    except ImportProcessingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found.",
        ) from exc
    except ImportProcessingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        ImportProcessingFileError,
        ImportProcessingMappingError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The import batch could not be processed.",
        ) from None

    return ImportProcessingResponse.model_validate(result)


@router.get(
    "/{import_batch_id}/result",
    response_model=ImportResultResponse,
    status_code=status.HTTP_200_OK,
)
def get_import_result_endpoint(
    import_batch_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("imports.upload"),
    ),
    db: Session = Depends(get_db_session),
) -> ImportResultResponse:
    """Retrieve persisted counts and row-level errors for the verified tenant."""
    try:
        result = get_import_result(
            db,
            organization_id=tenant_context.organization_id,
            import_batch_id=import_batch_id,
        )
    except ImportResultNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found.",
        ) from exc
    except ImportResultDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored import result could not be read.",
        ) from exc

    return ImportResultResponse.model_validate(result)


def _safe_csv_cell(value: object) -> str:
    """Prevent untrusted text from being interpreted as a spreadsheet formula."""
    text = str(value) if value is not None else ""
    probe = text.lstrip(" \t\r\n")

    if probe.startswith(("=", "+", "-", "@")):
        return "'" + text

    return text


@router.get(
    "/{import_batch_id}/errors.csv",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV report of persisted row-level import errors.",
        },
    },
)
def download_import_errors_endpoint(
    import_batch_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("imports.upload"),
    ),
    db: Session = Depends(get_db_session),
) -> Response:
    """Download persisted row-level errors for the verified tenant."""
    try:
        result = get_import_result(
            db,
            organization_id=tenant_context.organization_id,
            import_batch_id=import_batch_id,
        )
    except ImportResultNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import batch not found.",
        ) from exc
    except ImportResultDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored import result could not be read.",
        ) from exc

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["row_number", "field", "code", "message"])

    for error in result["errors"]:
        writer.writerow(
            [
                error["row_number"],
                _safe_csv_cell(error["field"]),
                _safe_csv_cell(error["code"]),
                _safe_csv_cell(error["message"]),
            ]
        )

    filename = f"import-{import_batch_id}-errors.csv"

    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )