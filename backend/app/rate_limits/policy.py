"""Rate-limit rules per governed execution type (E13 hardening).

A rule sets how many executions an organization and an individual actor may start in one window.
These are request limits. They are not usage budgets (see app/governance/usage_ledger.py) and they
are not provider quotas (see docs/architecture/rate-limits-budgets-and-quotas.md).

Defaults are conservative starting points. Per-organization overrides are not part of this change.
"""

from dataclasses import dataclass
from datetime import timedelta

AUTOMATION_DEAL_CREATED_EXECUTION = "automation.deal_created"

# Counters older than this are removed. They are operational state, not records. A window must be
# shorter than this, or cleanup could delete a window that is still active.
RETENTION = timedelta(days=2)


@dataclass(frozen=True)
class RateLimitRule:
    execution_type: str
    window: timedelta
    organization_limit: int
    actor_limit: int

    def __post_init__(self) -> None:
        if self.window <= timedelta(0):
            raise ValueError("A rate-limit window must be positive.")
        if self.window >= RETENTION:
            raise ValueError("A rate-limit window must be shorter than the counter retention period.")
        if self.organization_limit < 1 or self.actor_limit < 1:
            raise ValueError("Rate-limit values must be at least 1.")


RULES: dict[str, RateLimitRule] = {
    AUTOMATION_DEAL_CREATED_EXECUTION: RateLimitRule(
        execution_type=AUTOMATION_DEAL_CREATED_EXECUTION,
        window=timedelta(minutes=1),
        organization_limit=600,
        actor_limit=120,
    ),
}


def get_rule(execution_type: str) -> RateLimitRule:
    """Return the rule for an execution type. Unknown types raise, so the caller fails closed."""
    rule = RULES.get(execution_type)
    if rule is None:
        raise KeyError(f"No rate-limit rule is configured for {execution_type!r}.")
    return rule
