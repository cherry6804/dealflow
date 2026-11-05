"""The CRM actions an agent plan may name (DFR1-021).

A CRM action is the only way an agent writes to the CRM. Each action is a fixed key with a fixed argument list, a set of
permissions the initiating member must hold, and a flag saying whether it writes. Agents cannot add actions, and an action
never receives raw SQL, free text as a field name, or a permission from the agent.

This module holds only the static catalogue. It imports no services, so the configuration validator can use it without an import
cycle. The handlers live in ``crm_actions.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

INTAKE_PROCESS = "intake.process"
INTAKE_RESOLVE_IDENTITY = "intake.resolve_identity"
LEAD_CALCULATE_PRIORITY = "lead.calculate_priority"
QUALIFICATION_RECORD = "qualification.record"
MATCHING_EVALUATE = "matching.evaluate"


@dataclass(frozen=True)
class CrmActionSpec:
    key: str
    permissions: tuple[str, ...]
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...]
    writes: bool


CRM_ACTIONS: dict[str, CrmActionSpec] = {
    INTAKE_PROCESS: CrmActionSpec(
        key=INTAKE_PROCESS,
        permissions=("leads.create", "contacts.create"),
        required_arguments=("submission_id",),
        optional_arguments=(),
        writes=True,
    ),
    INTAKE_RESOLVE_IDENTITY: CrmActionSpec(
        key=INTAKE_RESOLVE_IDENTITY,
        permissions=("contacts.read",),
        required_arguments=("submission_id",),
        optional_arguments=(),
        writes=False,
    ),
    LEAD_CALCULATE_PRIORITY: CrmActionSpec(
        key=LEAD_CALCULATE_PRIORITY,
        permissions=("leads.update",),
        required_arguments=("lead_id",),
        optional_arguments=(),
        writes=True,
    ),
    MATCHING_EVALUATE: CrmActionSpec(
        key=MATCHING_EVALUATE,
        permissions=("requirements.update",),
        required_arguments=("requirement_id",),
        optional_arguments=(),
        writes=True,
    ),
    QUALIFICATION_RECORD: CrmActionSpec(
        key=QUALIFICATION_RECORD,
        permissions=("leads.update",),
        required_arguments=("lead_id", "score_id"),
        optional_arguments=("suggestion",),
        writes=True,
    ),
}
