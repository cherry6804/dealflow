"""Tenant-scoped knowledge ingestion and retrieval (DFR1-016).

Ingestion takes one available text document of the caller's organization, splits it into bounded chunks, embeds them through
the AI gateway, and stores the chunks with their embeddings. Retrieval embeds a query through the same gateway and returns the
best chunks with citations.

Rules enforced here, in order, on the server:

1. The caller holds ``documents.read`` in the organization (database check, as for every document read).
2. The document is available, belongs to the organization, and has an eligible classification (``ELIGIBLE_CLASSIFICATIONS``).
3. The content type is plain text and the bytes decode as strict UTF-8, within size and chunk limits.
4. Every embedding goes through the AI gateway, so the shared execution gate, budgets and provider rules apply.
5. Chunks are written only after every embedding succeeded. A failure leaves the previous chunks untouched.

Retrieved text is returned as data with ``untrusted=True``. This module never places retrieved text into an instruction
or a prompt. A caller that builds a prompt must keep retrieved text in a clearly separated data section.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_gateway.contracts import (
    MAX_EMBEDDING_INPUTS,
    MAX_INPUT_CHARACTERS,
    GatewayRequest,
)
from app.ai_gateway.service import execute as gateway_execute
from app.ai_gateway.tasks import TaskType
from app.auth.dependencies import CurrentUserContext
from app.db.models.document import Document
from app.db.models.knowledge_chunk import KnowledgeChunk
from app.documents.service import (
    DocumentDownloadUnavailableError,
    open_document_for_download,
)
from app.governance.execution_gate import actor_permission_granted

# Classifications eligible for AI ingestion. PROPOSAL: confidential and restricted documents are excluded until product
# approves otherwise. This is a product decision, recorded in the evidence document, not a settled rule.
ELIGIBLE_CLASSIFICATIONS: frozenset[str] = frozenset({Document.CLASSIFICATION_PUBLIC, Document.CLASSIFICATION_INTERNAL})
TEXT_CONTENT_TYPES: frozenset[str] = frozenset({"text/plain", "text/markdown", "text/csv"})

CHUNK_CHARACTERS = 1_000
CHUNK_OVERLAP = 100
MAX_DOCUMENT_BYTES = 1_000_000
MAX_CHUNKS_PER_DOCUMENT = 200
MAX_TOP_K = 10
CAPABILITY = "ai.document_processing"

REASON_OK = "ok"
REASON_UNCHANGED = "unchanged"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_DOCUMENT_UNAVAILABLE = "document_unavailable"
REASON_NOT_ELIGIBLE = "classification_not_eligible"
REASON_UNSUPPORTED_CONTENT = "unsupported_content"
REASON_TOO_LARGE = "content_too_large"
REASON_NOT_TEXT = "content_not_utf8_text"
REASON_EMPTY = "content_empty"
REASON_INVALID_QUERY = "invalid_query"
REASON_EMBEDDING_FAILED = "embedding_failed"

Sleep = Callable[[float], None]


@dataclass(frozen=True)
class IngestResult:
    outcome: str  # succeeded, unchanged, denied or failed
    reason_code: str
    chunk_count: int = 0
    embedding_reason: str | None = None


@dataclass(frozen=True)
class Citation:
    document_id: str
    display_name: str
    chunk_index: int


@dataclass(frozen=True)
class RetrievedChunk:
    citation: Citation
    text: str
    score: float
    untrusted: bool = True


@dataclass(frozen=True)
class RetrieveResult:
    outcome: str
    reason_code: str
    hits: tuple[RetrievedChunk, ...] = field(default=())


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping windows of at most ``CHUNK_CHARACTERS``. Empty windows are dropped."""
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    chunks: list[str] = []
    step = CHUNK_CHARACTERS - CHUNK_OVERLAP
    start = 0
    while start < len(normalized):
        piece = normalized[start:start + CHUNK_CHARACTERS].strip()
        if piece:
            chunks.append(piece)
        if start + CHUNK_CHARACTERS >= len(normalized):
            break
        start += step
    return chunks


def _embed(
    db: Session,
    *,
    user_context: CurrentUserContext,
    organization_id: UUID,
    texts: list[str],
    resource_id: str,
    sleep: Sleep,
) -> tuple[list[tuple[float, ...]], str | None]:
    """Embed texts in batches through the gateway. Returns the vectors, or the first gateway reason that stopped it."""
    vectors: list[tuple[float, ...]] = []
    for start in range(0, len(texts), MAX_EMBEDDING_INPUTS):
        batch = tuple(texts[start:start + MAX_EMBEDDING_INPUTS])
        result = gateway_execute(
            db,
            GatewayRequest(
                organization_id=organization_id,
                capability_key=CAPABILITY,
                task=TaskType.EMBEDDING,
                user_context=user_context,
                texts=batch,
                input_token_estimate=sum(len(item) // 4 + 1 for item in batch),
                resource_id=resource_id,
            ),
            sleep=sleep,
        )
        if not result.succeeded or len(result.vectors) != len(batch):
            return [], result.reason_code
        vectors.extend(result.vectors)
    return vectors, None


def ingest_document(
    db: Session,
    *,
    organization_id: UUID,
    document_id: UUID,
    user_context: CurrentUserContext,
    sleep: Sleep = time.sleep,
) -> IngestResult:
    """Index one available text document. The caller commits or rolls back the session."""
    if not actor_permission_granted(db, organization_id=organization_id, user_id=user_context.user.id,
                                       permission_key="documents.read"):
        return IngestResult(outcome="denied", reason_code=REASON_PERMISSION_DENIED)

    document = db.scalar(select(Document).where(
        Document.id == document_id,
        Document.organization_id == organization_id,
        Document.status == Document.STATUS_AVAILABLE,
    ))
    if document is None:
        return IngestResult(outcome="denied", reason_code=REASON_DOCUMENT_UNAVAILABLE)
    if document.access_classification not in ELIGIBLE_CLASSIFICATIONS:
        return IngestResult(outcome="denied", reason_code=REASON_NOT_ELIGIBLE)
    if (document.content_type or "") not in TEXT_CONTENT_TYPES:
        return IngestResult(outcome="denied", reason_code=REASON_UNSUPPORTED_CONTENT)
    if (document.file_size_bytes or 0) > MAX_DOCUMENT_BYTES:
        return IngestResult(outcome="denied", reason_code=REASON_TOO_LARGE)

    try:
        _, stream = open_document_for_download(db, organization_id=organization_id, document_id=document_id)
    except DocumentDownloadUnavailableError:
        return IngestResult(outcome="denied", reason_code=REASON_DOCUMENT_UNAVAILABLE)
    try:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    finally:
        stream.close()
    if len(raw) > MAX_DOCUMENT_BYTES:
        return IngestResult(outcome="denied", reason_code=REASON_TOO_LARGE)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return IngestResult(outcome="denied", reason_code=REASON_NOT_TEXT)

    pieces = chunk_text(text)
    if not pieces:
        return IngestResult(outcome="denied", reason_code=REASON_EMPTY)
    if len(pieces) > MAX_CHUNKS_PER_DOCUMENT:
        return IngestResult(outcome="denied", reason_code=REASON_TOO_LARGE)

    hashes = [hashlib.sha256(piece.encode("utf-8")).hexdigest() for piece in pieces]
    existing = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).all()
    if sorted(row.content_hash for row in existing) == sorted(hashes) and existing:
        return IngestResult(outcome="unchanged", reason_code=REASON_UNCHANGED, chunk_count=len(existing))

    vectors, embedding_reason = _embed(
        db,
        user_context=user_context,
        organization_id=organization_id,
        texts=pieces,
        resource_id=f"document:{document_id}",
        sleep=sleep,
    )
    if embedding_reason is not None:
        return IngestResult(outcome="failed", reason_code=REASON_EMBEDDING_FAILED, embedding_reason=embedding_reason)

    model = _model_name_for_chunks(db, organization_id=organization_id)
    for row in existing:
        db.delete(row)
    db.flush()
    for index, (piece, content_hash, vector) in enumerate(zip(pieces, hashes, vectors, strict=True)):
        db.add(KnowledgeChunk(
            organization_id=organization_id,
            document_id=document_id,
            chunk_index=index,
            content=piece,
            content_hash=content_hash,
            embedding_model=model,
            embedding=list(vector),
        ))
    db.flush()
    return IngestResult(outcome="succeeded", reason_code=REASON_OK, chunk_count=len(pieces))


def remove_document_chunks(db: Session, *, organization_id: UUID, document_id: UUID) -> int:
    """Delete the derived chunks of one document. Called when the document is archived or deleted."""
    rows = db.scalars(select(KnowledgeChunk).where(
        KnowledgeChunk.organization_id == organization_id,
        KnowledgeChunk.document_id == document_id,
    )).all()
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


def retrieve(
    db: Session,
    *,
    organization_id: UUID,
    user_context: CurrentUserContext,
    query: str,
    top_k: int = 5,
    sleep: Sleep = time.sleep,
) -> RetrieveResult:
    """Return the best chunks of the organization's eligible, available documents for a query, with citations."""
    if not actor_permission_granted(db, organization_id=organization_id, user_id=user_context.user.id,
                                       permission_key="documents.read"):
        return RetrieveResult(outcome="denied", reason_code=REASON_PERMISSION_DENIED)
    cleaned = query.strip()
    if not cleaned or len(cleaned) > MAX_INPUT_CHARACTERS or not 1 <= top_k <= MAX_TOP_K:
        return RetrieveResult(outcome="denied", reason_code=REASON_INVALID_QUERY)

    vectors, embedding_reason = _embed(
        db,
        user_context=user_context,
        organization_id=organization_id,
        texts=[cleaned],
        resource_id="knowledge:query",
        sleep=sleep,
    )
    if embedding_reason is not None or not vectors:
        return RetrieveResult(outcome="failed", reason_code=REASON_EMBEDDING_FAILED)
    query_vector = vectors[0]

    rows = db.execute(
        select(KnowledgeChunk, Document)
        .join(Document, Document.id == KnowledgeChunk.document_id)
        .where(
            KnowledgeChunk.organization_id == organization_id,
            Document.organization_id == organization_id,
            Document.status == Document.STATUS_AVAILABLE,
            Document.access_classification.in_(sorted(ELIGIBLE_CLASSIFICATIONS)),
        )
    ).all()

    scored = [
        (_cosine(query_vector, tuple(chunk.embedding)), chunk, document)
        for chunk, document in rows
    ]
    scored.sort(key=lambda item: (-item[0], str(item[1].document_id), item[1].chunk_index))
    hits = tuple(
        RetrievedChunk(
            citation=Citation(document_id=str(document.id), display_name=document.display_name,
                              chunk_index=chunk.chunk_index),
            text=chunk.content,
            score=round(score, 6),
        )
        for score, chunk, document in scored[:top_k]
    )
    return RetrieveResult(outcome="succeeded", reason_code=REASON_OK, hits=hits)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return 0.0 if norm == 0.0 else dot / norm


def _model_name_for_chunks(db: Session, *, organization_id: UUID) -> str:
    """The embedding model in use for this organization's embedding route, recorded on each chunk."""
    from app.ai_gateway.routing import resolve_route

    route = resolve_route(db, organization_id=organization_id, task=TaskType.EMBEDDING)
    return route.model if route is not None else "unknown"
