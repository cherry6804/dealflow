
"""FastAPI routes for tenant-scoped business documents."""

from collections.abc import Iterator
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.service import persist_document_access_audit_event
from app.authz.dependencies import require_permission
from app.db.models.audit_event import AuditDecision
from app.db.models.deal import Deal
from app.db.models.document import Document
from app.db.models.lead import Lead
from app.db.models.property import Property
from app.db.session import get_db_session
from app.documents.schemas import (
    DocumentAssociationRequest,
    DocumentListResponse,
    DocumentResponse,
)
from app.documents.service import (
    DocumentDownloadUnavailableError,
    DocumentUploadError,
    DocumentUploadTooLargeError,
    DocumentUploadValidationError,
    open_document_for_download,
    upload_document,
)
from app.storage import ObjectNotFoundError, StorageError
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

DOWNLOAD_CHUNK_SIZE = 64 * 1024


def _content_disposition(filename: str) -> str:
    """Build a safe attachment header with an ASCII fallback."""
    cleaned = filename.replace("\r", "").replace("\n", "").strip()
    if not cleaned:
        cleaned = "document"

    ascii_name = cleaned.encode("ascii", "ignore").decode("ascii")
    ascii_name = "".join(
        char if char.isalnum() or char in " ._-"
        else "_"
        for char in ascii_name
    ).strip(" .")

    if not ascii_name:
        ascii_name = "document"

    encoded_name = quote(cleaned, safe="")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )


def _stream_and_close(source) -> Iterator[bytes]:
    """Stream a file in bounded chunks and always close its handle."""
    try:
        while True:
            chunk = source.read(DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        source.close()


def _audit_document_download(
    *,
    tenant_context: TenantContext,
    document_id: UUID,
    decision: AuditDecision,
) -> None:
    """Persist a document-specific download audit event.

    Audit failures intentionally propagate: the download endpoint must not
    silently proceed when its required audit record cannot be persisted.
    """
    persist_document_access_audit_event(
        user_id=tenant_context.membership.user_id,
        organization_id=tenant_context.organization_id,
        document_id=document_id,
        decision=decision,
    )


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


@router.get(
    "",
    response_model=DocumentListResponse,
)
def list_documents_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None, min_length=1, max_length=50),
    tenant_context: TenantContext = Depends(
        require_permission("documents.read")
    ),
    db: Session = Depends(get_db_session),
) -> DocumentListResponse:
    """List available document metadata within the verified organization."""
    filters = [
        Document.organization_id == tenant_context.organization_id,
        Document.status == Document.STATUS_AVAILABLE,
    ]

    if category is not None:
        filters.append(Document.category == category.strip().upper())

    try:
        total = (
            db.scalar(
                select(func.count())
                .select_from(Document)
                .where(*filters)
            )
            or 0
        )

        documents = db.scalars(
            select(Document)
            .where(*filters)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The documents could not be listed.",
        ) from None

    return DocumentListResponse(
        items=[
            DocumentResponse.model_validate(document)
            for document in documents
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.patch(
    "/{document_id}/association",
    response_model=DocumentResponse,
)
def update_document_association_endpoint(
    document_id: UUID,
    payload: DocumentAssociationRequest,
    tenant_context: TenantContext = Depends(
        require_permission("documents.manage")
    ),
    db: Session = Depends(get_db_session),
) -> DocumentResponse:
    """Link or unlink an available document from a tenant-owned record."""
    organization_id = tenant_context.organization_id

    try:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
                Document.status == Document.STATUS_AVAILABLE,
            )
        )

        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            )

        # Validate the requested record before changing the document.
        if payload.record_type is not None and payload.record_id is not None:
            record_models = {
                "lead": Lead,
                "property": Property,
                "deal": Deal,
            }
            record_model = record_models[payload.record_type]

            record_exists = db.scalar(
                select(record_model.id).where(
                    record_model.id == payload.record_id,
                    record_model.organization_id == organization_id,
                )
            )

            if record_exists is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Business record not found.",
                )

        # Clear previous associations so only one record can be linked.
        document.lead_id = None
        document.property_id = None
        document.deal_id = None

        if payload.record_type == "lead":
            document.lead_id = payload.record_id
        elif payload.record_type == "property":
            document.property_id = payload.record_id
        elif payload.record_type == "deal":
            document.deal_id = payload.record_id

        db.commit()
        db.refresh(document)

    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document association could not be saved.",
        ) from None

    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download")
def download_document_endpoint(
    document_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("documents.download")
    ),
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    """Download an available document and audit its access outcome."""
    try:
        document, source = open_document_for_download(
            db,
            organization_id=tenant_context.organization_id,
            document_id=document_id,
        )
    except (DocumentDownloadUnavailableError, ObjectNotFoundError):
        # Use the same response for missing and cross-tenant documents.
        # The event identifies the requested ID without revealing whether
        # the document belongs to another organization.
        try:
            _audit_document_download(
                tenant_context=tenant_context,
                document_id=document_id,
                decision=AuditDecision.DENIED,
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The document access audit could not be recorded.",
            ) from None

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        ) from None
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document could not be downloaded.",
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document could not be downloaded.",
        ) from None

    try:
        _audit_document_download(
            tenant_context=tenant_context,
            document_id=document_id,
            decision=AuditDecision.ALLOWED,
        )
    except Exception:
        # Do not return a file stream if the required audit write failed.
        source.close()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The document access audit could not be recorded.",
        ) from None

    headers = {
        "Content-Disposition": _content_disposition(
            document.original_filename
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }

    return StreamingResponse(
        _stream_and_close(source),
        media_type=document.content_type or "application/octet-stream",
        headers=headers,
    )
