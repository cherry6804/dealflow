"""Test helpers for governance switches.

Deal-created automation is disabled by default (DFR1-006). Tests that exercise that
automation must enable it explicitly, as an organization administrator would.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.governance.capabilities import AUTOMATION_DEAL_CREATED_RULES, AUTOMATION_MASTER
from app.governance.service import set_capability_enabled


def enable_deal_created_automation(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
) -> None:
    """Turn on the automation master switch and the deal-created rules switch."""
    for capability_key in (AUTOMATION_MASTER, AUTOMATION_DEAL_CREATED_RULES):
        set_capability_enabled(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            capability_key=capability_key,
            is_enabled=True,
        )
