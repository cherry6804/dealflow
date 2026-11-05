"""Lead intake: record submissions, resolve identity, and create CRM records through the CRM services (DFR1-021).

A submission is stored first, exactly as received, whatever its validity. Processing then resolves identity against existing
contacts in the same organization and writes only through the contact and lead services. Repeated submissions with the same
reference return the stored submission, and a reused reference with different content is refused. An open lead for a matched
contact is reused, so processing never creates a second open lead for the same person.

Permissions are checked against the acting member on every operation, and an agent acts only as its initiating member. A
submission that cannot be matched with confidence is not written: it waits for a human decision, which is attributed to the member.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.attribution import user_attribution
from app.audit.independent import OUTCOME_COMPLETED, persist_independent_audit_event
from app.contacts.schemas import ContactCreateRequest
from app.contacts.service import ContactDuplicateError, create_contact
from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.db.models.lead_intake import LeadIntakeSubmission
from app.governance.execution_gate import actor_permission_granted
from app.imports.duplicate_detection import normalize_email
from app.leads.intake import (
    MAX_REFERENCE,
    OUTCOME_AMBIGUOUS,
    OUTCOME_MATCHED_CONTACT,
    OUTCOME_MATCHED_OPEN_LEAD,
    OUTCOME_NEW_CONTACT,
    IntakeCandidate,
    decide_match,
    email_key,
    name_agrees,
    payload_hash,
    raw_is_too_large,
    validate_intake,
)
from app.leads.schemas import LeadCreateRequest
from app.leads.service import create_lead

INTAKE_AUDIT_EVENT = "lead_intake"
SOURCE_CHANNELS = ("manual", "form", "api")
DECISION_ATTACH = "attach"
DECISION_CREATE_NEW = "create_new"
DECISION_REJECT = "reject"
DECISIONS = (DECISION_ATTACH, DECISION_CREATE_NEW, DECISION_REJECT)
CLOSED_LEAD_STATUSES = (Lead.STATUS_WON, Lead.STATUS_LOST)

REASON_PERMISSION_DENIED = "permission_denied"
REASON_NOT_FOUND = "submission_not_found"
REASON_INVALID = "invalid_submission"
REASON_IDEMPOTENCY_CONFLICT = "idempotency_conflict"
REASON_NOT_AWAITING_REVIEW = "not_awaiting_review"
REASON_NOT_A_CANDIDATE = "contact_not_a_candidate"
REASON_DUPLICATE_CONTACT = "duplicate_contact"
REASON_TOO_LARGE = "payload_too_large"
REASON_INVALID_REFERENCE = "invalid_external_reference"
REASON_INVALID_CHANNEL = "invalid_source_channel"
REASON_LEAD_NOT_FOUND = "lead_not_found"


class IntakeError(Exception):
    def __init__(self, reason: str, problems: list[str] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


def _require(db: Session, *, organization_id: UUID, actor_id: UUID, permissions: tuple[str, ...]) -> None:
    for permission in permissions:
        if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
            raise IntakeError(REASON_PERMISSION_DENIED, status=403)


def _audit(db: Session, *, organization_id: UUID, actor_id: UUID, submission: LeadIntakeSubmission, action: str,
           metadata: dict[str, Any]) -> None:
    # Identifiers and outcomes only. Names, email and phone are never written to the audit trail.
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=actor_id),
        event_type=INTAKE_AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key="leads.create",
        resource_type="lead_intake",
        resource_id=str(submission.id),
        metadata=dict(metadata, status=submission.status, source_channel=submission.source_channel),
    )


def submit_intake(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    source_channel: str,
    external_reference: str,
    payload: object,
) -> tuple[LeadIntakeSubmission, bool]:
    """Store one submission. Returns ``(submission, created)``. A repeated reference returns the stored submission."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permissions=("leads.create",))
    if source_channel not in SOURCE_CHANNELS:
        raise IntakeError(REASON_INVALID_CHANNEL, ["The source channel must be manual, form or api."], status=422)
    reference = external_reference.strip()
    if not reference or len(reference) > MAX_REFERENCE:
        raise IntakeError(REASON_INVALID_REFERENCE, ["The external reference must be 1 to 120 characters."], status=422)
    if raw_is_too_large(payload):
        raise IntakeError(REASON_TOO_LARGE, ["The submission is too large."], status=422)

    normalized, problems = validate_intake(payload)
    digest = payload_hash({"normalized": normalized, "problems": problems, "channel": source_channel}) \
        if normalized is not None else payload_hash({"raw": payload})

    existing = db.scalar(select(LeadIntakeSubmission).where(
        LeadIntakeSubmission.organization_id == organization_id,
        LeadIntakeSubmission.external_reference == reference,
    ))
    if existing is not None:
        if existing.payload_hash == digest:
            return existing, False
        raise IntakeError(REASON_IDEMPOTENCY_CONFLICT, ["This reference was used for a different submission."])

    submission = LeadIntakeSubmission(
        organization_id=organization_id,
        source_channel=source_channel,
        external_reference=reference,
        payload_hash=digest,
        raw_payload=payload if isinstance(payload, dict) else {"value": str(payload)},
        normalized_payload=normalized,
        validation_problems=problems,
        status=LeadIntakeSubmission.STATUS_INVALID if problems else LeadIntakeSubmission.STATUS_RECEIVED,
        candidate_contact_ids=[],
        submitted_by_user_id=actor_id,
    )
    db.add(submission)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
           action="lead_intake.submitted", metadata={"problem_count": len(problems)})
    return submission, True


def get_submission(db: Session, *, organization_id: UUID, submission_id: UUID) -> LeadIntakeSubmission:
    submission = db.scalar(select(LeadIntakeSubmission).where(
        LeadIntakeSubmission.id == submission_id,
        LeadIntakeSubmission.organization_id == organization_id,
    ))
    if submission is None:
        raise IntakeError(REASON_NOT_FOUND, status=404)
    return submission


def list_submissions(db: Session, *, organization_id: UUID, limit: int = 50) -> list[LeadIntakeSubmission]:
    return list(db.scalars(
        select(LeadIntakeSubmission)
        .where(LeadIntakeSubmission.organization_id == organization_id)
        .order_by(LeadIntakeSubmission.created_at.desc(), LeadIntakeSubmission.id.desc())
        .limit(max(1, min(limit, 100)))
    ).all())


def identity_candidates(db: Session, *, organization_id: UUID, normalized: dict[str, Any]) -> list[IntakeCandidate]:
    """Existing contacts in this organization that share the submitted email or phone. Read-only."""
    email = email_key(normalized)
    phone = normalized.get("phone")
    if not email and not phone:
        return []
    clauses = []
    if email:
        clauses.append(func.lower(func.trim(Contact.email)) == email)
    if phone:
        clauses.append(func.regexp_replace(Contact.phone, r"[^0-9]", "", "g") == phone)
    rows = db.scalars(select(Contact).where(Contact.organization_id == organization_id, or_(*clauses))).all()
    candidates: list[IntakeCandidate] = []
    for contact in rows:
        candidates.append(IntakeCandidate(
            contact_id=str(contact.id),
            email_match=bool(email) and normalize_email(contact.email) == email,
            phone_match=bool(phone) and "".join(ch for ch in (contact.phone or "") if ch.isdigit()) == phone,
            name_match=name_agrees(normalized, contact.first_name, contact.last_name),
        ))
    return candidates


def _open_lead(db: Session, *, organization_id: UUID, contact_id: UUID) -> Lead | None:
    return db.scalar(select(Lead).where(
        Lead.organization_id == organization_id,
        Lead.contact_id == contact_id,
        Lead.is_active.is_(True),
        Lead.status.not_in(CLOSED_LEAD_STATUSES),
    ).order_by(Lead.created_at.desc()).limit(1))


def _lock(db: Session, *, organization_id: UUID, submission_id: UUID) -> LeadIntakeSubmission:
    submission = db.scalar(select(LeadIntakeSubmission).where(
        LeadIntakeSubmission.id == submission_id,
        LeadIntakeSubmission.organization_id == organization_id,
    ).with_for_update())
    if submission is None:
        raise IntakeError(REASON_NOT_FOUND, status=404)
    return submission


def _apply(db: Session, *, organization_id: UUID, actor_id: UUID, submission: LeadIntakeSubmission,
           outcome: str, contact_id: UUID | None) -> LeadIntakeSubmission:
    """Write the CRM records for a submission through the CRM services, then mark it processed."""
    normalized = submission.normalized_payload or {}
    if contact_id is None:
        _require(db, organization_id=organization_id, actor_id=actor_id, permissions=("contacts.create",))
        try:
            contact = create_contact(
                db,
                organization_id=organization_id,
                payload=ContactCreateRequest(
                    first_name=str(normalized["first_name"]),
                    last_name=normalized.get("last_name"),
                    email=normalized.get("email"),
                    phone=normalized.get("phone"),
                ),
            )
        except ContactDuplicateError as error:
            raise IntakeError(REASON_DUPLICATE_CONTACT, ["A contact with this email or phone already exists."]) from error
        contact_id = contact.id
        outcome = OUTCOME_NEW_CONTACT

    open_lead = _open_lead(db, organization_id=organization_id, contact_id=contact_id)
    if open_lead is not None:
        lead_id = open_lead.id
        outcome = OUTCOME_MATCHED_OPEN_LEAD
    else:
        _require(db, organization_id=organization_id, actor_id=actor_id, permissions=("leads.create",))
        lead = create_lead(db, organization_id=organization_id, payload=LeadCreateRequest(
            contact_id=contact_id, interest=normalized.get("interest"),
        ))
        if lead is None:
            raise IntakeError(REASON_LEAD_NOT_FOUND, status=404)
        lead_id = lead.id
    submission.contact_id = contact_id
    submission.lead_id = lead_id
    submission.match_outcome = outcome
    submission.status = LeadIntakeSubmission.STATUS_PROCESSED
    submission.processed_at = datetime.now(UTC)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
           action="lead_intake.processed", metadata={"outcome": outcome, "lead_id": str(lead_id)})
    return submission


def process_submission(db: Session, *, organization_id: UUID, actor_id: UUID, submission_id: UUID) -> LeadIntakeSubmission:
    """Resolve identity and write the CRM records. Idempotent: a processed or rejected submission is returned unchanged."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permissions=("leads.create",))
    submission = _lock(db, organization_id=organization_id, submission_id=submission_id)
    if submission.status in (LeadIntakeSubmission.STATUS_PROCESSED, LeadIntakeSubmission.STATUS_REJECTED):
        return submission
    if submission.status == LeadIntakeSubmission.STATUS_INVALID:
        raise IntakeError(REASON_INVALID, submission.validation_problems)
    if submission.status == LeadIntakeSubmission.STATUS_NEEDS_REVIEW:
        return submission  # Waiting for a human decision. The agent does not decide an uncertain match.

    normalized = submission.normalized_payload or {}
    candidates = identity_candidates(db, organization_id=organization_id, normalized=normalized)
    outcome = decide_match(normalized, candidates)
    if outcome == OUTCOME_AMBIGUOUS:
        submission.status = LeadIntakeSubmission.STATUS_NEEDS_REVIEW
        submission.match_outcome = OUTCOME_AMBIGUOUS
        submission.candidate_contact_ids = [item.contact_id for item in candidates]
        db.flush()
        _audit(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
               action="lead_intake.needs_review", metadata={"candidate_count": len(candidates)})
        return submission
    contact_id = UUID(candidates[0].contact_id) if candidates else None
    try:
        return _apply(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
                      outcome=outcome, contact_id=contact_id)
    except IntakeError as error:
        if error.reason != REASON_DUPLICATE_CONTACT:
            raise
        # A contact already holds this email or phone (for example an inactive one). A person decides, so nothing is written.
        submission.status = LeadIntakeSubmission.STATUS_NEEDS_REVIEW
        submission.match_outcome = OUTCOME_AMBIGUOUS
        db.flush()
        return submission


def decide_submission(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    submission_id: UUID,
    decision: str,
    contact_id: UUID | None = None,
    reason: str | None = None,
) -> LeadIntakeSubmission:
    """Record a human decision on an uncertain submission, then apply it. The decision is attributed to the member."""
    if decision not in DECISIONS:
        raise IntakeError("invalid_decision", ["The decision must be attach, create_new or reject."], status=422)
    _require(db, organization_id=organization_id, actor_id=actor_id, permissions=("leads.update",))
    submission = _lock(db, organization_id=organization_id, submission_id=submission_id)
    if submission.status != LeadIntakeSubmission.STATUS_NEEDS_REVIEW or submission.decision is not None:
        raise IntakeError(REASON_NOT_AWAITING_REVIEW)

    submission.decision = decision
    submission.decision_reason = (reason or "").strip()[:500] or None
    submission.decided_by_user_id = actor_id
    db.flush()
    if decision == DECISION_REJECT:
        submission.status = LeadIntakeSubmission.STATUS_REJECTED
        db.flush()
        _audit(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
               action="lead_intake.rejected", metadata={})
        return submission
    if decision == DECISION_ATTACH:
        if contact_id is None or str(contact_id) not in (submission.candidate_contact_ids or []):
            raise IntakeError(REASON_NOT_A_CANDIDATE, ["Attach only to a contact the submission matched."], status=422)
        _audit(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
               action="lead_intake.decided", metadata={"decision": decision})
        return _apply(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
                      outcome=OUTCOME_MATCHED_CONTACT, contact_id=contact_id)
    _audit(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
           action="lead_intake.decided", metadata={"decision": decision})
    return _apply(db, organization_id=organization_id, actor_id=actor_id, submission=submission,
                  outcome=OUTCOME_NEW_CONTACT, contact_id=None)
