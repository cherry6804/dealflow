
"""FastAPI routes for business document uploads."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.models.document import Document
from app.db.session import get_db_session
from app.documents.schemas import DocumentResponse
from app.documents.service import (
    DocumentUploadError,
    DocumentUploadTooLargeError,
    DocumentUploadValidationError,
    upload_document,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post(
    "/uploads",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_endpoint(
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None, max_length=255),
    description: str | None = Form(default=None, max_length=20_000),
    category: str = Form(default=Document.CATEGORY_OTHER),
    document_type: str = Form(..., min_length=1, max_length=100),
    access_classification: str = Form(
        default=Document.CLASSIFICATION_INTERNAL
    ),
    tenant_context: TenantContext = Depends(
        require_permission("documents.upload")
    ),
    db: Session = Depends(get_db_session),
) -> DocumentResponse:
    """Upload a private document for the verified tenant."""
    try:
        document = await upload_document(
            db,
            organization_id=tenant_context.organization_id,
            user_id=tenant_context.membership.user_id,
            file=file,
            display_name=display_name,
            description=description,
            category=category,
            document_type=document_type,
            access_classification=access_classification,
        )
    except DocumentUploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except DocumentUploadValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except DocumentUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document metadata could not be saved.",
        ) from None
    finally:
        await file.close()

    return DocumentResponse.model_validate(document)
