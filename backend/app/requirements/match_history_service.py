"""Persistence and retrieval for customer requirement matching history."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.properties.matching_service import get_property_match_results
from app.requirements.history_service import build_customer_requirement_snapshot


def _json_value(value: Any) -> Any:
    """Convert Pydantic models and nested values to JSON-safe Python data."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]

    return value


def create_requirement_match_run(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
    actor_id: UUID,
) -> tuple[RequirementMatchRun, list[RequirementMatchRunResult]]:
    """Execute matching and persist immutable snapshots for this run.

    The caller owns the transaction and must commit on success or roll back
    on failure. The requirement must be active when a new run is created.
    """

    requirement = db.scalar(
        select(CustomerRequirement).where(
            CustomerRequirement.id == requirement_id,
            CustomerRequirement.organization_id == organization_id,
            CustomerRequirement.status == CustomerRequirement.STATUS_ACTIVE,
            CustomerRequirement.is_active.is_(True),
        )
    )

    if requirement is None:
        raise ValueError("Active customer requirement not found.")

    # Snapshot the requirement criteria at the time of matching.
    criteria_snapshot = build_customer_requirement_snapshot(
        db,
        requirement=requirement,
        organization_id=organization_id,
    )

    # Reuse the established matching algorithm.
    match_results = get_property_match_results(
        db,
        organization_id=organization_id,
        requirement_id=requirement_id,
    )

    run = RequirementMatchRun(
        organization_id=organization_id,
        customer_requirement_id=requirement_id,
        actor_id=actor_id,
        criteria_snapshot=_json_value(criteria_snapshot),
        total_candidates=len(match_results),
        matched_candidates=sum(
            1 for result in match_results if result.overall_match
        ),
    )

    db.add(run)
    db.flush()

    saved_results: list[RequirementMatchRunResult] = []

    for result in match_results:
        saved = RequirementMatchRunResult(
            organization_id=organization_id,
            match_run_id=run.id,
            property_id=result.property.id,
            overall_match=result.overall_match,
            property_snapshot=_json_value(result.property),
            criteria_results_snapshot=_json_value(result.criteria),
        )
        db.add(saved)
        saved_results.append(saved)

    db.flush()
    db.refresh(run)

    return run, saved_results


def list_requirement_match_runs(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
) -> list[RequirementMatchRun]:
    """List historical runs, including runs for deleted requirements.

    Tenant scoping is enforced through organization_id. The historical
    requirement ID deliberately has no live-requirement existence check.
    """

    statement = (
        select(RequirementMatchRun)
        .where(
            RequirementMatchRun.organization_id == organization_id,
            RequirementMatchRun.customer_requirement_id == requirement_id,
        )
        .order_by(
            RequirementMatchRun.created_at.asc(),
            RequirementMatchRun.id.asc(),
        )
    )

    return list(db.scalars(statement).all())


def list_requirement_match_run_results(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
    run_id: UUID,
) -> list[RequirementMatchRunResult]:
    """List saved snapshots for a run scoped to its tenant and requirement.

    No live-requirement lookup is required, so results remain retrievable
    after the original customer requirement has been deleted.
    """

    run = db.scalar(
        select(RequirementMatchRun).where(
            RequirementMatchRun.id == run_id,
            RequirementMatchRun.organization_id == organization_id,
            RequirementMatchRun.customer_requirement_id == requirement_id,
        )
    )

    if run is None:
        raise ValueError("Match run not found.")

    statement = (
        select(RequirementMatchRunResult)
        .where(
            RequirementMatchRunResult.match_run_id == run.id,
            RequirementMatchRunResult.organization_id == organization_id,
        )
        .order_by(RequirementMatchRunResult.id.asc())
    )

    return list(db.scalars(statement).all())
