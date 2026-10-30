"""Read and change organization capability settings, with an audit record per change."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.governance.capabilities import (
    CAPABILITIES,
    CAPABILITY_BY_KEY,
    CapabilityDefinition,
)
from app.governance.policy import PolicyDecision, evaluate_capability

GOVERNANCE_EVENT_TYPE = "governance"
GOVERNANCE_CAPABILITY_ACTION = "governance.capability.updated"


class UnknownCapabilityError(LookupError):
    """Raised when a request names a capability the catalogue does not define."""


@dataclass(frozen=True)
class CapabilityState:
    definition: CapabilityDefinition
    is_enabled: bool
    policy_version: int
    updated_at: datetime | None
    decision: PolicyDecision


def _setting_map(db: Session, organization_id: UUID) -> dict[str, OrganizationCapabilitySetting]:
    return {
        row.capability_key: row
        for row in db.scalars(
            select(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == organization_id
            )
        ).all()
    }


def list_capability_states(db: Session, *, organization_id: UUID) -> list[CapabilityState]:
    """Return every catalogue capability with its stored switch and effective decision."""
    settings = _setting_map(db, organization_id)
    states: list[CapabilityState] = []
    for definition in CAPABILITIES:
        row = settings.get(definition.key)
        states.append(
            CapabilityState(
                definition=definition,
                is_enabled=row.is_enabled if row is not None else definition.default_enabled,
                policy_version=row.policy_version if row is not None else 0,
                updated_at=row.updated_at if row is not None else None,
                decision=evaluate_capability(
                    db, organization_id=organization_id, capability_key=definition.key
                ),
            )
        )
    return states


def set_capability_enabled(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    capability_key: str,
    is_enabled: bool,
    correlation_id: str | None = None,
) -> CapabilityState:
    """Persist a switch change, bump the policy version and write an audit event.

    The caller owns the transaction. The row is locked so concurrent changes to the
    same capability serialize and the policy version increases monotonically.
    """
    if capability_key not in CAPABILITY_BY_KEY:
        raise UnknownCapabilityError(capability_key)

    row = db.scalar(
        select(OrganizationCapabilitySetting)
        .where(
            OrganizationCapabilitySetting.organization_id == organization_id,
            OrganizationCapabilitySetting.capability_key == capability_key,
        )
        .with_for_update()
    )
    before = row.is_enabled if row is not None else CAPABILITY_BY_KEY[capability_key].default_enabled
    previous_version = row.policy_version if row is not None else 0

    if row is None:
        row = OrganizationCapabilitySetting(
            organization_id=organization_id,
            capability_key=capability_key,
            is_enabled=is_enabled,
            policy_version=previous_version + 1,
            updated_by_user_id=actor_user_id,
        )
        db.add(row)
    else:
        row.is_enabled = is_enabled
        row.policy_version = previous_version + 1
        row.updated_by_user_id = actor_user_id
    db.flush()

    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=GOVERNANCE_EVENT_TYPE,
            action=GOVERNANCE_CAPABILITY_ACTION,
            decision="allowed",
            permission_key="governance.capabilities.manage",
            resource_type="organization_capability",
            resource_id=capability_key,
            correlation_id=correlation_id,
            event_metadata=json.dumps(
                {
                    "before": before,
                    "after": is_enabled,
                    "policy_version": row.policy_version,
                },
                sort_keys=True,
            ),
        )
    )
    db.flush()

    definition = CAPABILITY_BY_KEY[capability_key]
    return CapabilityState(
        definition=definition,
        is_enabled=row.is_enabled,
        policy_version=row.policy_version,
        updated_at=row.updated_at,
        decision=evaluate_capability(
            db,
            organization_id=organization_id,
            capability_key=capability_key,
            correlation_id=correlation_id,
        ),
    )
