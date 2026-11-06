"""Export and clearing rules for derived and operational Dealsflo records (DFR1-050).

Each table here belongs to a category in ``data_classification``. The rules are the only place that decides what a
deletion clears from these tables:

- A clearing rule names a model, the fields that hold personal free text, and the value each field is set to. The
  value is ``None``, the redaction placeholder, or an empty container. Structure, identifiers, statuses, counts and
  financial values are never listed, so they are never changed.
- Exporters emit a fixed set of fields. Secrets, credential material, internal prompts, agent and workflow
  definitions, and idempotency keys are never emitted.

The mapping was reviewed against the model columns. It is recorded in
``docs/architecture/dfr1-050-privacy-gap-matrix.md``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.activity import Activity
from app.db.models.agent import AgentExecution, AgentExecutionStep
from app.db.models.ai_pricing import AiProviderCostEntry
from app.db.models.automation_execution import AutomationExecution
from app.db.models.customer_profile import CustomerProfile
from app.db.models.deal import Deal
from app.db.models.deal_negotiation import DealNegotiationHistory
from app.db.models.deal_stage_history import DealStageHistory
from app.db.models.document_review import DocumentReview
from app.db.models.follow_up import FollowUp
from app.db.models.human_task import HumanTask, HumanTaskEvent
from app.db.models.knowledge_chunk import KnowledgeChunk
from app.db.models.lead import Lead
from app.db.models.lead_intake import LeadIntakeSubmission, LeadQualificationResult
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.db.models.next_best_action import NextBestActionRecommendation
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.workflow_execution import WorkflowExecution, WorkflowExecutionStep

PLACEHOLDER = "Redacted"

# Categories whose approved fields a deletion clears (decision B for CRM; the same rule for derived records).
CLEAR_NONE = "none"
CLEAR_PLACEHOLDER = "placeholder"
CLEAR_EMPTY_OBJECT = "empty_object"
CLEAR_EMPTY_LIST = "empty_list"
# Tombstones are derived from the row ID, the table and the field name only. They never depend on the content, so
# they cannot be checked against personal data, and they keep unique and not-null columns valid.
CLEAR_TOMBSTONE_DIGEST = "tombstone_digest"
CLEAR_TOMBSTONE_TEXT = "tombstone_text"


def tombstone_digest(row: object, field_name: str) -> str:
    table = getattr(row, "__tablename__", type(row).__name__)
    return hashlib.sha256(f"redacted:{table}:{row.id}:{field_name}".encode()).hexdigest()


def tombstone_text(row: object) -> str:
    return f"redacted-{row.id}"


@dataclass(frozen=True)
class ClearField:
    field: str
    clear_to: str

    def target(self, row: object, current: Any) -> Any:
        if self.clear_to == CLEAR_NONE:
            return None
        if self.clear_to == CLEAR_PLACEHOLDER:
            return PLACEHOLDER
        if self.clear_to == CLEAR_EMPTY_OBJECT:
            return {}
        if self.clear_to == CLEAR_TOMBSTONE_DIGEST:
            return tombstone_digest(row, self.field)
        if self.clear_to == CLEAR_TOMBSTONE_TEXT:
            return tombstone_text(row)
        return []

    def is_cleared(self, row: object, current: Any) -> bool:
        return current == self.target(row, current)


@dataclass(frozen=True)
class ClearRule:
    model: type
    fields: tuple[ClearField, ...]
    # Fields left unchanged on purpose, named for the reviewer.
    kept: tuple[str, ...] = ()


def _f(field: str, clear_to: str) -> ClearField:
    return ClearField(field, clear_to)


CLEARING_RULES: dict[str, tuple[ClearRule, ...]] = {
    "crm.leads": (
        ClearRule(Lead, (_f("next_action", CLEAR_NONE),), kept=("status", "interest", "outcome", "next_action_at")),
    ),
    "crm.follow_ups": (
        ClearRule(FollowUp, (_f("title", CLEAR_PLACEHOLDER), _f("description", CLEAR_NONE)), kept=("due_at", "status")),
        ClearRule(
            Activity,
            (_f("title", CLEAR_PLACEHOLDER), _f("description", CLEAR_NONE), _f("details", CLEAR_NONE)),
            kept=("activity_type", "occurred_at"),
        ),
    ),
    "crm.customer_profiles": (ClearRule(CustomerProfile, (_f("customer_notes", CLEAR_NONE),), kept=("is_active",)),),
    "crm.deals": (
        ClearRule(Deal, (_f("notes", CLEAR_NONE),), kept=("stage", "expected_value", "currency")),
        ClearRule(DealNegotiationHistory, (_f("note", CLEAR_NONE),), kept=("state", "created_at")),
        ClearRule(DealStageHistory, (_f("reason", CLEAR_NONE),), kept=("from_stage", "to_stage", "created_at")),
    ),
    "crm.lead_intelligence": (
        # The score and band are kept. Their explanations (factors, requirement summary) are personal facts.
        ClearRule(LeadPriorityScore, (_f("factors", CLEAR_EMPTY_LIST), _f("requirement_summary", CLEAR_EMPTY_LIST),
                                      _f("input_hash", CLEAR_TOMBSTONE_DIGEST)),
                  kept=("score", "band", "ruleset_version", "computed_at")),
        ClearRule(LeadPriorityCorrection, (_f("reason", CLEAR_PLACEHOLDER),), kept=("corrected_band", "corrected_score")),
    ),
    "crm.lead_intake": (
        # The raw payload is the submitter's own data. The fingerprint and the decision stay as evidence.
        ClearRule(
            LeadIntakeSubmission,
            (_f("raw_payload", CLEAR_EMPTY_OBJECT), _f("normalized_payload", CLEAR_NONE),
             _f("validation_problems", CLEAR_EMPTY_LIST), _f("decision_reason", CLEAR_NONE),
             _f("external_reference", CLEAR_TOMBSTONE_TEXT), _f("payload_hash", CLEAR_TOMBSTONE_DIGEST)),
            kept=("source_channel", "status", "match_outcome", "decision", "contact_id", "lead_id", "processed_at"),
        ),
    ),
    "crm.lead_qualification": (
        ClearRule(LeadQualificationResult, (_f("findings", CLEAR_EMPTY_OBJECT), _f("review_reason", CLEAR_NONE)),
                  kept=("review_status", "requires_review", "reviewed_at")),
    ),
    "crm.requirement_matching": (
        ClearRule(RequirementMatchRun, (_f("criteria_snapshot", CLEAR_EMPTY_OBJECT), _f("input_hash", CLEAR_TOMBSTONE_DIGEST)),
                  kept=("total_candidates", "matched_candidates", "created_at")),
        ClearRule(NextBestActionRecommendation,
                  (_f("facts", CLEAR_EMPTY_OBJECT), _f("summary", CLEAR_PLACEHOLDER), _f("history", CLEAR_EMPTY_LIST)),
                  kept=("category", "status", "priority", "decided_at")),
    ),
    "ai.execution_traces": (
        ClearRule(AgentExecution, (_f("input_values", CLEAR_EMPTY_OBJECT), _f("output", CLEAR_NONE),
                                   _f("failure_reason", CLEAR_NONE), _f("input_hash", CLEAR_TOMBSTONE_DIGEST)),
                  kept=("status", "tool_calls", "model_calls", "steps_completed", "created_at")),
        ClearRule(AgentExecutionStep, (_f("trace", CLEAR_EMPTY_OBJECT),), kept=("kind", "status", "attempts")),
    ),
    "automation.workflow_runs": (
        ClearRule(WorkflowExecution, (_f("input_values", CLEAR_EMPTY_OBJECT), _f("output", CLEAR_NONE),
                                      _f("failure_reason", CLEAR_NONE), _f("input_hash", CLEAR_TOMBSTONE_DIGEST)),
                  kept=("status", "trigger_type", "steps_completed", "created_at")),
        ClearRule(WorkflowExecutionStep, (_f("trace", CLEAR_NONE),), kept=("step_type", "status", "attempts")),
    ),
    "automation.human_tasks": (
        ClearRule(HumanTask, (_f("title", CLEAR_PLACEHOLDER), _f("instructions", CLEAR_NONE),
                              _f("decision_comment", CLEAR_NONE)),
                  kept=("kind", "status", "decided_at", "due_at")),
    ),
    "automation.rule_runs": (
        ClearRule(AutomationExecution, (_f("action_results", CLEAR_EMPTY_LIST), _f("error_message", CLEAR_NONE)),
                  kept=("status", "event_type", "started_at", "completed_at")),
    ),
}

RULE_CATEGORIES: frozenset[str] = frozenset(CLEARING_RULES)


# Personal-data history that deletion keeps on purpose. Each entry names what is kept and why. Any future redaction
# of these records needs a separately approved security design: the append-only trigger and the audit controls are
# not bypassed by privacy processing.
RETAINED_PERSONAL_DATA_HISTORY: tuple[dict[str, str], ...] = (
    {
        "table": "human_task_events",
        "kept": "Decision and assignment events (created, assigned, reassigned, approved, rejected, expired, cancelled) "
        "and comment events, with their comment and detail text.",
        "why": "Mandatory approval evidence. Comment events are part of the same append-only history.",
        "limitation": "Comment text can contain personal information. Deletion cannot change it: the database rejects "
        "every UPDATE and DELETE on this table. Export includes it for the data subject. Redaction needs a "
        "separately approved security design.",
    },
)

# What this export and its deletions do not cover. Listed in every artifact.
PRIVACY_LIMITATIONS: tuple[dict[str, str], ...] = (
    {
        "topic": "Human task event history",
        "statement": "Comment and decision text in human_task_events is retained, not deleted. "
        "See retained_personal_data_history.",
    },
    {
        "topic": "Messages and conversations",
        "statement": "No producer exists. Not exported, not deleted, and not claimed as checked.",
    },
    {
        "topic": "Calls, voice recordings and transcripts",
        "statement": "No producer exists. Not exported, not deleted, and not claimed as checked.",
    },
    {
        "topic": "AI chat prompts and responses",
        "statement": "No conversational producer is persisted. Agent run content is covered under ai.execution_traces.",
    },
    {
        "topic": "Provider-side copies",
        "statement": "No provider integration performs deletion. Deletion here applies only to Dealsflo's own records.",
    },
    {
        "topic": "Retention periods",
        "statement": "No retention period has been approved for the categories listed here. Only documents and "
        "invitations can be enforced, and only where an organization administrator has configured a period.",
    },
    {
        "topic": "Lead intake fingerprint",
        "statement": "The payload digest is replaced when the submission is cleared, because an unsalted digest of "
        "contact details can be checked against guessed values.",
    },
)

# Records a clearing cannot change. Reported on every deletion of the category, as retained, never as deleted or
# anonymized. Human task events are append-only: the database trigger rejects every UPDATE and DELETE on the table.
# They are retained in full because decision and assignment events are mandatory approval evidence, and comment events
# are part of the same history. Changing this needs a decision on the immutability control, not a privacy workaround.
RETAINED_RECORDS: dict[str, tuple[str, ...]] = {
    "automation.human_tasks": (
        "retained: human_task_events (mandatory approval evidence and comment history, append-only, not altered)",
    ),
}


def pending_clearing(db: Session, organization_id: UUID, category_key: str) -> list[tuple[Any, ClearRule]]:
    """Rows whose approved fields still hold personal content, with the rule that applies to each."""
    found: list[tuple[Any, ClearRule]] = []
    for rule in CLEARING_RULES.get(category_key, ()):
        for row in db.scalars(select(rule.model).where(rule.model.organization_id == organization_id)).all():
            if any(not item.is_cleared(row, getattr(row, item.field)) for item in rule.fields):
                found.append((row, rule))
    return found


def apply_clearing(db: Session, organization_id: UUID, category_key: str) -> int:
    """Clear the approved fields and return how many rows changed. Structure and keys are untouched."""
    changed = 0
    for row, rule in pending_clearing(db, organization_id, category_key):
        for item in rule.fields:
            if not item.is_cleared(row, getattr(row, item.field)):
                setattr(row, item.field, item.target(row, getattr(row, item.field)))
        changed += 1
    db.flush()
    return changed


def kept_fields(category_key: str) -> tuple[str, ...]:
    """Fields a clearing leaves in place, named per model, for the audit record."""
    return tuple(
        f"{rule.model.__tablename__}.{name}"
        for rule in CLEARING_RULES.get(category_key, ())
        for name in rule.kept
    )


# ---------------------------------------------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _id(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def export_lead_priority_scores(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LeadPriorityScore).where(LeadPriorityScore.organization_id == organization_id)
        .order_by(LeadPriorityScore.created_at, LeadPriorityScore.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "lead_id": str(row.lead_id),
            "ruleset_version": row.ruleset_version,
            "score": row.score,
            "band": row.band,
            "method": row.method,
            "confidence": row.confidence,
            "insufficient_data": row.insufficient_data,
            "factors": row.factors,
            "missing_factors": row.missing_factors,
            "requirement_summary": row.requirement_summary,
            "computed_at": _iso(row.computed_at),
        }
        for row in rows
    ]


def export_lead_priority_corrections(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LeadPriorityCorrection).where(LeadPriorityCorrection.organization_id == organization_id)
        .order_by(LeadPriorityCorrection.created_at, LeadPriorityCorrection.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "score_id": str(row.score_id),
            "lead_id": str(row.lead_id),
            "corrected_band": row.corrected_band,
            "corrected_score": row.corrected_score,
            "reason": row.reason,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_next_best_actions(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(NextBestActionRecommendation)
        .where(NextBestActionRecommendation.organization_id == organization_id)
        .order_by(NextBestActionRecommendation.created_at, NextBestActionRecommendation.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "customer_requirement_id": str(row.customer_requirement_id),
            "match_run_id": str(row.match_run_id),
            "category": row.category,
            "basis": row.basis,
            "status": row.status,
            "priority": row.priority,
            "summary": row.summary,
            "subject_property_id": _id(row.subject_property_id),
            "facts": row.facts,
            "history": row.history,
            "decided_at": _iso(row.decided_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_lead_intake(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LeadIntakeSubmission).where(LeadIntakeSubmission.organization_id == organization_id)
        .order_by(LeadIntakeSubmission.created_at, LeadIntakeSubmission.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "source_channel": row.source_channel,
            "external_reference": row.external_reference,
            "raw_payload": row.raw_payload,
            "normalized_payload": row.normalized_payload,
            "validation_problems": row.validation_problems,
            "status": row.status,
            "match_outcome": row.match_outcome,
            "contact_id": _id(row.contact_id),
            "lead_id": _id(row.lead_id),
            "decision": row.decision,
            "decision_reason": row.decision_reason,
            "processed_at": _iso(row.processed_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_lead_qualifications(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LeadQualificationResult).where(LeadQualificationResult.organization_id == organization_id)
        .order_by(LeadQualificationResult.created_at, LeadQualificationResult.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "lead_id": str(row.lead_id),
            "execution_id": str(row.execution_id),
            "findings": row.findings,
            "requires_review": row.requires_review,
            "review_status": row.review_status,
            "review_reason": row.review_reason,
            "reviewed_at": _iso(row.reviewed_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_agent_executions(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Agent runs with their inputs and outputs. Definitions, versions, prompts and idempotency keys are not exported."""
    rows = db.scalars(
        select(AgentExecution).where(AgentExecution.organization_id == organization_id)
        .order_by(AgentExecution.created_at, AgentExecution.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "agent_id": str(row.agent_id),
            "agent_version_id": str(row.agent_version_id),
            "status": row.status,
            "input_values": row.input_values,
            "output": row.output,
            "failure_reason": row.failure_reason,
            "tool_calls": row.tool_calls,
            "model_calls": row.model_calls,
            "steps_completed": row.steps_completed,
            "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_agent_steps(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(AgentExecutionStep).where(AgentExecutionStep.organization_id == organization_id)
        .order_by(AgentExecutionStep.execution_id, AgentExecutionStep.step_index)
    ).all()
    return [
        {
            "id": str(row.id),
            "execution_id": str(row.execution_id),
            "step_index": row.step_index,
            "kind": row.kind,
            "status": row.status,
            "reason_code": row.reason_code,
            "attempts": row.attempts,
            "trace": row.trace,
            "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
        }
        for row in rows
    ]


def export_workflow_runs(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(WorkflowExecution).where(WorkflowExecution.organization_id == organization_id)
        .order_by(WorkflowExecution.created_at, WorkflowExecution.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "workflow_id": str(row.workflow_id),
            "version_number": row.version_number,
            "status": row.status,
            "trigger_type": row.trigger_type,
            "input_values": row.input_values,
            "output": row.output,
            "failure_reason": row.failure_reason,
            "steps_completed": row.steps_completed,
            "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_workflow_steps(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(WorkflowExecutionStep).where(WorkflowExecutionStep.organization_id == organization_id)
        .order_by(WorkflowExecutionStep.execution_id, WorkflowExecutionStep.step_index)
    ).all()
    return [
        {
            "id": str(row.id),
            "execution_id": str(row.execution_id),
            "step_id": row.step_id,
            "step_index": row.step_index,
            "step_type": row.step_type,
            "status": row.status,
            "reason_code": row.reason_code,
            "attempts": row.attempts,
            "trace": row.trace,
            "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
        }
        for row in rows
    ]


def export_human_tasks(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(HumanTask).where(HumanTask.organization_id == organization_id)
        .order_by(HumanTask.created_at, HumanTask.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "kind": row.kind,
            "status": row.status,
            "title": row.title,
            "instructions": row.instructions,
            "assigned_to_user_id": _id(row.assigned_to_user_id),
            "requested_by_user_id": str(row.requested_by_user_id),
            "due_at": _iso(row.due_at),
            "decided_by_user_id": _id(row.decided_by_user_id),
            "decided_at": _iso(row.decided_at),
            "decision_comment": row.decision_comment,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_human_task_events(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(HumanTaskEvent).where(HumanTaskEvent.organization_id == organization_id)
        .order_by(HumanTaskEvent.created_at, HumanTaskEvent.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "task_id": str(row.task_id),
            "event_type": row.event_type,
            "comment": row.comment,
            "detail": row.detail,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_automation_runs(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(AutomationExecution).where(AutomationExecution.organization_id == organization_id)
        .order_by(AutomationExecution.created_at, AutomationExecution.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "rule_id": str(row.rule_id),
            "event_type": row.event_type,
            "status": row.status,
            "action_results": row.action_results,
            "error_message": row.error_message,
            "started_at": _iso(row.started_at),
            "completed_at": _iso(row.completed_at),
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_document_reviews(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(DocumentReview).where(DocumentReview.organization_id == organization_id)
        .order_by(DocumentReview.reviewed_at, DocumentReview.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "document_id": str(row.document_id),
            "method": row.method,
            "page_count": row.page_count,
            "title": row.title,
            "author": row.author,
            "summary_text": row.summary_text,
            "summary_page": row.summary_page,
            "fields": row.fields,
            "reviewed_at": _iso(row.reviewed_at),
        }
        for row in rows
    ]


def export_knowledge_chunks(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Chunk text and metadata. Embedding vectors are derived numbers and are not exported."""
    rows = db.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.organization_id == organization_id)
        .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index)
    ).all()
    return [
        {
            "id": str(row.id),
            "document_id": str(row.document_id),
            "chunk_index": row.chunk_index,
            "content": row.content,
            "content_hash": row.content_hash,
            "embedding_model": row.embedding_model,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def export_cost_entries(db: Session, organization_id: UUID) -> list[dict[str, Any]]:
    """Provider cost per settled usage unit. A financial record: metering only, no content."""
    rows = db.scalars(
        select(AiProviderCostEntry).where(AiProviderCostEntry.organization_id == organization_id)
        .order_by(AiProviderCostEntry.occurred_at, AiProviderCostEntry.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "usage_event_id": str(row.usage_event_id),
            "provider_key": row.provider_key,
            "model": row.model,
            "unit": row.unit,
            "quantity": row.quantity,
            "status": row.status,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
            "reason_code": row.reason_code,
            "occurred_at": _iso(row.occurred_at),
        }
        for row in rows
    ]


Exporter = Callable[[Session, UUID], list[dict[str, Any]]]

# Categories exported from the derived tables above, and the sub-records each one carries.
DERIVED_EXPORTERS: dict[str, Exporter] = {
    "crm.lead_intelligence": export_lead_priority_scores,
    "crm.lead_intake": export_lead_intake,
    "crm.lead_qualification": export_lead_qualifications,
    "ai.execution_traces": export_agent_executions,
    "automation.workflow_runs": export_workflow_runs,
    "automation.human_tasks": export_human_tasks,
    "automation.rule_runs": export_automation_runs,
    "ai.embeddings": export_knowledge_chunks,
}

DERIVED_SUB_RECORD_EXPORTERS: dict[str, dict[str, Exporter]] = {
    "crm.requirement_matching": {"next_best_actions": export_next_best_actions},
    "crm.lead_intelligence": {"corrections": export_lead_priority_corrections},
    "ai.execution_traces": {"steps": export_agent_steps},
    "automation.workflow_runs": {"steps": export_workflow_steps},
    "automation.human_tasks": {"events": export_human_task_events},
    "documents.files": {"reviews": export_document_reviews},
    "ai.usage": {"cost_entries": export_cost_entries},
}
