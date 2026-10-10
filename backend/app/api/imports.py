
"""Data import API routes for DealFlow."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.imports.schemas import ImportBatchResponse
from app.imports.service import (
    UploadTooLargeError,
    UploadValidationError,
    upload_import_source,
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
