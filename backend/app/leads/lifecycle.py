"""Lead lifecycle and business-state validation for DealFlow."""

from __future__ import annotations

from app.db.models.lead import Lead


ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    Lead.STATUS_NEW: frozenset(
        {
            Lead.STATUS_CONTACTED,
            Lead.STATUS_QUALIFIED,
            Lead.STATUS_ON_HOLD,
        }
    ),
    Lead.STATUS_CONTACTED: frozenset(
        {
            Lead.STATUS_QUALIFIED,
            Lead.STATUS_MATCHING,
            Lead.STATUS_ON_HOLD,
        }
    ),
    Lead.STATUS_QUALIFIED: frozenset(
        {
            Lead.STATUS_MATCHING,
            Lead.STATUS_VISIT,
            Lead.STATUS_ON_HOLD,
        }
    ),
    Lead.STATUS_MATCHING: frozenset(
        {
            Lead.STATUS_VISIT,
            Lead.STATUS_QUALIFIED,
            Lead.STATUS_ON_HOLD,
        }
    ),
    Lead.STATUS_VISIT: frozenset(
        {
            Lead.STATUS_MATCHING,
            Lead.STATUS_NEGOTIATION,
            Lead.STATUS_QUALIFIED,
            Lead.STATUS_ON_HOLD,
        }
    ),
    Lead.STATUS_NEGOTIATION: frozenset(
        {
            Lead.STATUS_WON,
            Lead.STATUS_LOST,
            Lead.STATUS_VISIT,
            Lead.STATUS_ON_HOLD,
        }
    ),
    Lead.STATUS_ON_HOLD: frozenset(
        {
            Lead.STATUS_CONTACTED,
            Lead.STATUS_QUALIFIED,
            Lead.STATUS_MATCHING,
            Lead.STATUS_VISIT,
            Lead.STATUS_NEGOTIATION,
        }
    ),
    Lead.STATUS_WON: frozenset(),
    Lead.STATUS_LOST: frozenset(),
}


TERMINAL_STATUSES = frozenset(
    {
        Lead.STATUS_WON,
        Lead.STATUS_LOST,
    }
)


TERMINAL_OUTCOMES = {
    Lead.STATUS_WON: Lead.OUTCOME_SUCCESSFUL,
    Lead.STATUS_LOST: Lead.OUTCOME_UNSUCCESSFUL,
}


def is_terminal_status(status: str) -> bool:
    """Return whether the supplied Lead status is terminal."""
    return status in TERMINAL_STATUSES


def is_valid_status_transition(
    current_status: str,
    new_status: str,
) -> bool:
    """Return whether a Lead may transition to the requested status."""
    if current_status == new_status:
        return True

    allowed_destinations = ALLOWED_STATUS_TRANSITIONS.get(current_status)

    if allowed_destinations is None:
        return False

    return new_status in allowed_destinations


def validate_status_transition(
    current_status: str,
    new_status: str,
) -> None:
    """Validate a requested Lead lifecycle transition."""
    if new_status not in Lead.STATUS_VALUES:
        raise ValueError(f"Invalid Lead status: {new_status}.")

    if current_status not in Lead.STATUS_VALUES:
        raise ValueError(
            f"Invalid current Lead status: {current_status}."
        )

    if not is_valid_status_transition(
        current_status=current_status,
        new_status=new_status,
    ):
        raise ValueError(
            f"Lead status transition from "
            f"{current_status} to {new_status} is not allowed."
        )


def validate_status_outcome(
    status: str,
    outcome: str | None,
) -> None:
    """Validate Lead status and outcome consistency."""
    if status not in Lead.STATUS_VALUES:
        raise ValueError(f"Invalid Lead status: {status}.")

    if outcome is not None and outcome not in Lead.OUTCOME_VALUES:
        raise ValueError(f"Invalid Lead outcome: {outcome}.")

    required_outcome = TERMINAL_OUTCOMES.get(status)

    if required_outcome is not None and outcome != required_outcome:
        raise ValueError(
            f"Lead status {status} requires outcome {required_outcome}."
        )