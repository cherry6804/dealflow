"""Store lead priority results and record human corrections (DFR1-020).

Every operation runs in the caller's organization and checks the caller's permission: reading needs ``leads.read``, computing a
score and recording a correction need ``leads.update``. Each computation and each correction writes an independent audit record,
attributed to the acting user. A correction is idempotent under its key: a repeat with the same key and score returns the stored
correction, and the same key with a different score is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.attribution import user_attribution
from app.audit.independent import OUTCOME_COMPLETED, persist_independent_audit_event
from app.db.models.lead import Lead
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.governance.execution_gate import actor_permission_granted
from app.leads.priority import BANDS, compute_priority

PRIORITY_AUDIT_EVENT = "lead_priority"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_LEAD_NOT_FOUND = "lead_not_found"
REASON_SCORE_NOT_FOUND = "score_not_found"
REASON_NOT_APPLICABLE = "lead_closed_or_inactive"
REASON_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
MAX_HISTORY = 50
MAX_REASON = 500
MAX_KEY = 120


class PriorityError(Exception):
    def __init__(self, reason: str, problems: list[str] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


def _require(db: Session, *, organization_id: UUID, actor_id: UUID, permission: str) -> None:
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
        raise PriorityError(REASON_PERMISSION_DENIED, status=403)


def _lead(db: Session, *, organization_id: UUID, lead_id: UUID) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.organization_id == organization_id))
    if lead is None:
        raise PriorityError(REASON_LEAD_NOT_FOUND, status=404)
    return lead


def _audit(db: Session, *, organization_id: UUID, actor_id: UUID, action: str, lead_id: UUID,
           metadata: dict[str, Any]) -> None:
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=actor_id),
        event_type=PRIORITY_AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key="leads.update",
        resource_type="lead",
        resource_id=str(lead_id),
        metadata=metadata,
    )


def calculate_and_store(db: Session, *, organization_id: UUID, actor_id: UUID, lead_id: UUID,
                        now: datetime | None = None) -> LeadPriorityScore:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="leads.update")
    _lead(db, organization_id=organization_id, lead_id=lead_id)
    result = compute_priority(db, organization_id=organization_id, lead_id=lead_id, now=now)
    if result.outcome == "not_applicable":
        raise PriorityError(REASON_NOT_APPLICABLE, ["A won, lost or inactive lead has no priority to compute."], status=409)
    assert result.score is not None and result.band is not None and result.method is not None
    assert result.confidence is not None and result.computed_at is not None and result.input_hash is not None
    row = LeadPriorityScore(
        organization_id=organization_id,
        lead_id=lead_id,
        ruleset_version=result.ruleset_version,
        score=result.score,
        band=result.band,
        method=result.method,
        confidence=result.confidence,
        insufficient_data=result.insufficient_data,
        factors=[factor.as_dict() for factor in result.factors],
        missing_factors=list(result.missing_factors),
        requirement_summary=list(result.requirements),
        input_hash=result.input_hash,
        computed_at=result.computed_at,
        computed_by_user_id=actor_id,
    )
    db.add(row)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="lead.priority.calculated", lead_id=lead_id,
           metadata={"score_id": str(row.id), "band": row.band, "method": row.method,
                     "ruleset_version": row.ruleset_version, "insufficient_data": row.insufficient_data})
    return row


def list_scores(db: Session, *, organization_id: UUID, actor_id: UUID, lead_id: UUID,
                limit: int = 10) -> list[LeadPriorityScore]:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="leads.read")
    _lead(db, organization_id=organization_id, lead_id=lead_id)
    bounded = max(1, min(limit, MAX_HISTORY))
    return list(db.scalars(
        select(LeadPriorityScore)
        .where(LeadPriorityScore.organization_id == organization_id, LeadPriorityScore.lead_id == lead_id)
        .order_by(LeadPriorityScore.computed_at.desc(), LeadPriorityScore.id.desc())
        .limit(bounded)
    ).all())


def list_corrections(db: Session, *, organization_id: UUID, actor_id: UUID, lead_id: UUID,
                     score_id: UUID) -> list[LeadPriorityCorrection]:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="leads.read")
    _score(db, organization_id=organization_id, lead_id=lead_id, score_id=score_id)
    return list(db.scalars(
        select(LeadPriorityCorrection)
        .where(LeadPriorityCorrection.organization_id == organization_id, LeadPriorityCorrection.score_id == score_id)
        .order_by(LeadPriorityCorrection.created_at, LeadPriorityCorrection.id)
        .limit(MAX_HISTORY)
    ).all())


def _score(db: Session, *, organization_id: UUID, lead_id: UUID, score_id: UUID) -> LeadPriorityScore:
    row = db.scalar(select(LeadPriorityScore).where(
        LeadPriorityScore.id == score_id,
        LeadPriorityScore.organization_id == organization_id,
        LeadPriorityScore.lead_id == lead_id,
    ))
    if row is None:
        raise PriorityError(REASON_SCORE_NOT_FOUND, status=404)
    return row


def record_correction(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    lead_id: UUID,
    score_id: UUID,
    corrected_band: str | None,
    corrected_score: int | None,
    reason: str,
    idempotency_key: str,
) -> tuple[LeadPriorityCorrection, bool]:
    """Record a human correction against one score. Returns (correction, created)."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="leads.update")
    _lead(db, organization_id=organization_id, lead_id=lead_id)
    score = _score(db, organization_id=organization_id, lead_id=lead_id, score_id=score_id)
    problems: list[str] = []
    if corrected_band is None and corrected_score is None:
        problems.append("A correction needs a corrected band, a corrected score, or both.")
    if corrected_band is not None and corrected_band not in BANDS:
        problems.append("The corrected band must be high, medium or low.")
    if corrected_score is not None and not 0 <= corrected_score <= 100:
        problems.append("The corrected score must be from 0 to 100.")
    cleaned_reason = reason.strip()
    if not cleaned_reason or len(cleaned_reason) > MAX_REASON:
        problems.append("A reason of 1 to 500 characters is required.")
    key = idempotency_key.strip()
    if not key or len(key) > MAX_KEY:
        problems.append("The idempotency key must be 1 to 120 characters.")
    if problems:
        raise PriorityError("invalid_correction", problems, status=422)

    existing = db.scalar(select(LeadPriorityCorrection).where(
        LeadPriorityCorrection.organization_id == organization_id,
        LeadPriorityCorrection.idempotency_key == key,
    ))
    if existing is not None:
        if existing.score_id == score.id:
            return existing, False
        raise PriorityError(REASON_IDEMPOTENCY_CONFLICT, ["This idempotency key was used for another request."])

    row = LeadPriorityCorrection(
        organization_id=organization_id,
        score_id=score.id,
        lead_id=lead_id,
        corrected_band=corrected_band,
        corrected_score=corrected_score,
        reason=cleaned_reason,
        idempotency_key=key,
        actor_user_id=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        # A concurrent request with the same key won the race. Its correction is the answer.
        winner = db.scalar(select(LeadPriorityCorrection).where(
            LeadPriorityCorrection.organization_id == organization_id,
            LeadPriorityCorrection.idempotency_key == key,
        ))
        if winner is not None and winner.score_id == score.id:
            return winner, False
        raise PriorityError(REASON_IDEMPOTENCY_CONFLICT, ["This idempotency key was used for another request."])
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="lead.priority.corrected", lead_id=lead_id,
           metadata={"score_id": str(score.id), "corrected_band": corrected_band,
                     "corrected_score": corrected_score, "recorded_at": datetime.now(UTC).isoformat()})
    return row, True
