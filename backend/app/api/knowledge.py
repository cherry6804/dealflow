"""Knowledge ingestion and retrieval over HTTP (DFR1-016).

Both routes require ``documents.read`` in the verified organization. Ingestion also goes through the AI gateway, so the
execution gate, budgets and audit apply. Search results are data: each hit carries ``untrusted_data: true``, and the response
never contains instructions. Callers must keep retrieved text out of any instruction section of a prompt.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai_gateway.contracts import MAX_INPUT_CHARACTERS
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.knowledge.service import MAX_TOP_K, ingest_document, retrieve
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


class IngestResponse(BaseModel):
    outcome: str
    reason_code: str
    chunk_count: int
    embedding_reason: str | None = None


class CitationResponse(BaseModel):
    document_id: str
    display_name: str
    chunk_index: int


class HitResponse(BaseModel):
    citation: CitationResponse
    text: str
    score: float
    untrusted_data: bool


class SearchResponse(BaseModel):
    outcome: str
    reason_code: str
    untrusted_data: bool = True
    hits: list[HitResponse]


@router.post("/documents/{document_id}/ingest", response_model=IngestResponse)
def ingest_document_endpoint(
    document_id: UUID,
    tenant: TenantContext = Depends(require_permission("documents.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> IngestResponse:
    """Index one document now. Repeating it with unchanged content is a no-op."""
    result = ingest_document(
        db,
        organization_id=tenant.organization_id,
        document_id=document_id,
        user_context=user_context,
    )
    db.commit()
    return IngestResponse(
        outcome=result.outcome,
        reason_code=result.reason_code,
        chunk_count=result.chunk_count,
        embedding_reason=result.embedding_reason,
    )


@router.get("/search", response_model=SearchResponse)
def search_endpoint(
    query: str = Query(min_length=1, max_length=MAX_INPUT_CHARACTERS),
    top_k: int = Query(default=5, ge=1, le=MAX_TOP_K),
    tenant: TenantContext = Depends(require_permission("documents.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> SearchResponse:
    """Return the best matching chunks of the organization's eligible documents, with citations."""
    result = retrieve(
        db,
        organization_id=tenant.organization_id,
        user_context=user_context,
        query=query,
        top_k=top_k,
    )
    db.commit()
    return SearchResponse(
        outcome=result.outcome,
        reason_code=result.reason_code,
        hits=[
            HitResponse(
                citation=CitationResponse(
                    document_id=hit.citation.document_id,
                    display_name=hit.citation.display_name,
                    chunk_index=hit.citation.chunk_index,
                ),
                text=hit.text,
                score=hit.score,
                untrusted_data=hit.untrusted,
            )
            for hit in result.hits
        ],
    )
