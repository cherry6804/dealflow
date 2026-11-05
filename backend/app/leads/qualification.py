"""Lead qualification findings, recorded per agent execution, and human review of them (DFR1-021).

A qualification result is built from the stored DFR1-020 score, never from a fresh calculation, so the findings describe exactly
the score the agent produced. The result keeps five kinds of content apart:

- ``verified_crm_facts``: values read from the lead and its contact at the time of the run.
- ``rule_findings``: the DFR1-020 score, band, method, confidence and the factors that earned points.
- ``missing_information``: fields the CRM does not hold. These are never guessed.
- ``recommended_next_actions``: rule-based suggestions, each labelled with its basis.
- ``ai_suggestions``: text produced by a model step. It is labelled unverified and is never shown as a fact.

``human_decisions`` starts empty and is filled only by a review. A review changes the review fields of the result and nothing
on the lead, so an agent never overwrites a human change, and the result shows whether the lead changed after it was recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.attribution import user_attribution
from app.audit.independent import OUTCOME_COMPLETED, persist_independent_audit_event
from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.db.models.lead_intake import LeadQualificationResult
from app.db.models.lead_priority import LeadPriorityScore
from app.governance.execution_gate import actor_permission_granted

QUALIFICATION_AUDIT_EVENT = "lead_qualification"
MAX_SUGGESTION = 300
REVIEW_ACCEPT = "accept"
REVIEW_OVERRIDE = "override"
REVIEW_DECISIONS = (REVIEW_ACCEPT, REVIEW_OVERRIDE)

REASON_PERMISSION_DENIED = "permission_denied"
REASON_LEAD_NOT_FOUND = "lead_not_found"
REASON_SCORE_MISMATCH = "score_not_for_lead"
REASON_NOT_FOUND = "qualification_not_found"
REASON_ALREADY_REVIEWED = "already_reviewed"
REASON_REVIEW_REASON_REQUIRED = "review_reason_required"


class QualificationError(Exception):
    def __init__(self, reason: str, problems: list[str] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


def _require(db: Session, *, organization_id: UUID, actor_id: UUID, permission: str) -> None:
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
        raise QualificationError(REASON_PERMISSION_DENIED, status=403)


def _factor_by_key(factors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key")): item for item in factors}


def _recommendations(score: LeadPriorityScore, missing: set[str], contact_email: bool, contact_phone: bool) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if not (contact_email or contact_phone):
        actions.append({"action": "Collect an email address or a phone number.", "basis": "rule"})
    if "budget" in missing:
        actions.append({"action": "Record the customer's budget.", "basis": "rule"})
    if "follow_up" in missing:
        actions.append({"action": "Schedule a follow-up.", "basis": "rule"})
    if score.band == "high":
        actions.append({"action": "Prioritise contact with this lead.", "basis": "rule"})
    elif score.band == "low" and not score.insufficient_data:
        actions.append({"action": "Review the lead before investing more effort.", "basis": "rule"})
    return actions


def build_findings(
    *,
    lead: Lead,
    contact: Contact | None,
    score: LeadPriorityScore,
    suggestion: str | None,
) -> dict[str, Any]:
    """The structured findings for one lead and one stored score. Pure: reads only the objects it is given."""
    missing = set(score.missing_factors or [])
    contact_email = bool(contact and contact.email)
    contact_phone = bool(contact and contact.phone)

    missing_information: list[dict[str, str]] = [{"field": key, "source": "priority_factor"} for key in sorted(missing)]
    if not contact_email:
        missing_information.append({"field": "email", "source": "contact"})
    if not contact_phone:
        missing_information.append({"field": "phone", "source": "contact"})

    reasons: list[str] = []
    if score.insufficient_data:
        reasons.append("insufficient_data")
    if not (contact_email or contact_phone):
        reasons.append("no_contact_route")
    if score.confidence == "low":
        reasons.append("low_confidence")

    ai = []
    if suggestion:
        text = suggestion.strip()[:MAX_SUGGESTION]
        if text:
            ai.append({"text": text, "basis": "ai_suggestion", "verified": False})

    return {
        "verified_crm_facts": {
            "lead_id": str(lead.id),
            "lead_status": lead.status,
            "lead_interest": lead.interest,
            "contact_id": str(lead.contact_id),
            "contact_has_email": contact_email,
            "contact_has_phone": contact_phone,
            "requirements_on_record": len(score.requirement_summary or []),
            "lead_updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        },
        "rule_findings": {
            "score_id": str(score.id),
            "score": score.score,
            "band": score.band,
            "method": score.method,
            "confidence": score.confidence,
            "insufficient_data": score.insufficient_data,
            "ruleset_version": score.ruleset_version,
            "computed_at": score.computed_at.isoformat(),
            "factors": [
                {"key": item.get("key"), "label": item.get("label"), "points": item.get("points"),
                 "max_points": item.get("max_points"), "known": item.get("known"), "observed": item.get("observed")}
                for item in score.factors or []
            ],
        },
        "missing_information": missing_information,
        "recommended_next_actions": _recommendations(score, missing, contact_email, contact_phone),
        "ai_suggestions": ai,
        "human_decisions": [],
        "escalation": {"requires_review": bool(reasons), "reasons": reasons},
    }


def record_qualification(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    execution_id: UUID,
    lead_id: UUID,
    score_id: UUID,
    suggestion: str | None,
) -> tuple[LeadQualificationResult, bool]:
    """Store the findings for one execution. Returns ``(result, created)``. A repeated call for the same execution is a no-op."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="leads.update")
    existing = db.scalar(select(LeadQualificationResult).where(LeadQualificationResult.execution_id == execution_id))
    if existing is not None:
        return existing, False

    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.organization_id == organization_id))
    if lead is None:
        raise QualificationError(REASON_LEAD_NOT_FOUND, status=404)
    score = db.scalar(select(LeadPriorityScore).where(
        LeadPriorityScore.id == score_id,
        LeadPriorityScore.organization_id == organization_id,
        LeadPriorityScore.lead_id == lead_id,
    ))
    if score is None:
        raise QualificationError(REASON_SCORE_MISMATCH, ["The score does not belong to this lead."], status=422)
    contact = db.scalar(select(Contact).where(Contact.id == lead.contact_id, Contact.organization_id == organization_id))

    findings = build_findings(lead=lead, contact=contact, score=score, suggestion=suggestion)
    requires_review = bool(findings["escalation"]["requires_review"])
    row = LeadQualificationResult(
        organization_id=organization_id,
        lead_id=lead_id,
        execution_id=execution_id,
        score_id=score.id,
        findings=findings,
        requires_review=requires_review,
        lead_updated_at=lead.updated_at,
        review_status=LeadQualificationResult.REVIEW_PENDING,
        recorded_by_user_id=actor_id,
    )
    db.add(row)
    db.flush()
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=actor_id),
        event_type=QUALIFICATION_AUDIT_EVENT,
        action="lead.qualification.recorded",
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key="leads.update",
        resource_type="lead",
        resource_id=str(lead_id),
        metadata={"qualification_id": str(row.id), "score_id": str(score.id), "requires_review": requires_review},
    )
    return row, True


def list_qualifications(db: Session, *, organization_id: UUID, actor_id: UUID, lead_id: UUID,
                        limit: int = 20) -> list[LeadQualificationResult]:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="leads.read")
    if db.scalar(select(Lead.id).where(Lead.id == lead_id, Lead.organization_id == organization_id)) is None:
        raise QualificationError(REASON_LEAD_NOT_FOUND, status=404)
    return list(db.scalars(
        select(LeadQualificationResult)
        .where(LeadQualificationResult.organization_id == organization_id, LeadQualificationResult.lead_id == lead_id)
        .order_by(LeadQualificationResult.created_at.desc(), LeadQualificationResult.id.desc())
        .limit(max(1, min(limit, 50)))
    ).all())


def review_qualification(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    qualification_id: UUID,
    decision: str,
    reason: str | None,
) -> LeadQualificationResult:
    """Record the member's decision on a result. Only the review fields change; the lead and the score do not."""
    if decision not in REVIEW_DECISIONS:
        raise QualificationError("invalid_decision", ["The decision must be accept or override."], status=422)
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="leads.update")
    row = db.scalar(select(LeadQualificationResult).where(
        LeadQualificationResult.id == qualification_id,
        LeadQualificationResult.organization_id == organization_id,
    ).with_for_update())
    if row is None:
        raise QualificationError(REASON_NOT_FOUND, status=404)
    if row.review_status != LeadQualificationResult.REVIEW_PENDING:
        raise QualificationError(REASON_ALREADY_REVIEWED)
    cleaned = (reason or "").strip()[:500] or None
    if decision == REVIEW_OVERRIDE and not cleaned:
        raise QualificationError(REASON_REVIEW_REASON_REQUIRED, ["An override needs a reason."], status=422)

    now = datetime.now(UTC)
    row.review_status = LeadQualificationResult.REVIEW_ACCEPTED if decision == REVIEW_ACCEPT \
        else LeadQualificationResult.REVIEW_OVERRIDDEN
    row.review_reason = cleaned
    row.reviewed_by_user_id = actor_id
    row.reviewed_at = now
    findings = dict(row.findings)
    findings["human_decisions"] = [{
        "decision": decision,
        "reason": cleaned,
        "decided_by_user_id": str(actor_id),
        "decided_at": now.isoformat(),
    }]
    row.findings = findings
    db.flush()
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=actor_id),
        event_type=QUALIFICATION_AUDIT_EVENT,
        action="lead.qualification.reviewed",
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key="leads.update",
        resource_type="lead",
        resource_id=str(row.lead_id),
        metadata={"qualification_id": str(row.id), "decision": decision},
    )
    return row


def is_stale(db: Session, row: LeadQualificationResult) -> bool:
    """True when the lead changed after the result was recorded, so the findings may no longer describe it."""
    current = db.scalar(select(Lead.updated_at).where(Lead.id == row.lead_id, Lead.organization_id == row.organization_id))
    return current is not None and row.lead_updated_at is not None and current > row.lead_updated_at
