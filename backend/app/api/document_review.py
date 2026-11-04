"""Reviewable document extraction over HTTP (DFR1-035).

Both routes require ``documents.read`` in the verified organization. Every value in a review is copied from the document or
produced by OCR or a model, so the response is marked ``untrusted_data: true``. Callers must show the values as document
content, never as instructions. Each field states its evidence basis and confidence, and model or OCR output is never a
verified fact.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.multimodal.review import (
    DISCLAIMER,
    REASON_NOT_FOUND,
    DocumentReviewView,
    ReviewResult,
    get_document_review,
    review_document,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/documents", tags=["document-review"])


class FieldResponse(BaseModel):
    key: str
    label: str
    value: str
    page_number: int
    evidence: str
    evidence_basis: str
    confidence: str


class SummaryResponse(BaseModel):
    text: str
    page_number: int


class ReviewBody(BaseModel):
    disclaimer: str
    method: str
    provider_key: str | None
    model: str | None
    page_count: int
    title: str | None
    author: str | None
    summary: SummaryResponse | None
    fields: list[FieldResponse]


class ReviewResponse(BaseModel):
    outcome: str
    reason_code: str
    untrusted_data: bool = True
    review: ReviewBody | None = None


def _body(view: DocumentReviewView) -> ReviewBody:
    return ReviewBody(
        disclaimer=DISCLAIMER,
        method=view.method,
        provider_key=view.provider_key,
        model=view.model,
        page_count=view.page_count,
        title=view.title,
        author=view.author,
        summary=SummaryResponse(text=view.summary.text, page_number=view.summary.page_number) if view.summary else None,
        fields=[
            FieldResponse(key=field.key, label=field.label, value=field.value, page_number=field.page_number,
                          evidence=field.evidence, evidence_basis=field.evidence_basis, confidence=field.confidence)
            for field in view.fields
        ],
    )


def _response(result: ReviewResult) -> ReviewResponse:
    return ReviewResponse(
        outcome=result.outcome,
        reason_code=result.reason_code,
        review=_body(result.review) if result.review is not None else None,
    )


@router.post("/{document_id}/review", response_model=ReviewResponse)
def review_document_endpoint(
    document_id: UUID,
    tenant: TenantContext = Depends(require_permission("documents.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> ReviewResponse:
    """Review one PDF and store the result, replacing any earlier review of the same document."""
    result = review_document(db, organization_id=tenant.organization_id, document_id=document_id, user_context=user_context)
    db.commit()
    return _response(result)


@router.get("/{document_id}/review", response_model=ReviewResponse)
def get_review_endpoint(
    document_id: UUID,
    tenant: TenantContext = Depends(require_permission("documents.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> ReviewResponse:
    """Return the stored review of an available document."""
    result = get_document_review(db, organization_id=tenant.organization_id, document_id=document_id, user_context=user_context)
    if result.reason_code == REASON_NOT_FOUND:
        raise HTTPException(status_code=404, detail=REASON_NOT_FOUND)
    return _response(result)
