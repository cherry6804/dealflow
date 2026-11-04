"""AI task types and the usage units each one meters (DFR1-015, DFR1-017).

A task type names what the caller wants done. The usage units name what is metered. Units are the same names the usage
ledger stores (``app.governance.usage_ledger.UsageUnit``), so usage from the gateway lands in the existing budget.
"""

from __future__ import annotations

from enum import StrEnum

from app.governance.usage_ledger import UsageUnit


class TaskType(StrEnum):
    TEXT = "text"
    EMBEDDING = "embedding"
    SPEECH = "speech"
    MULTIMODAL = "multimodal"


# Units metered for each task type. Speech and multimodal are declared here so routing can name them, but no adapter
# implements them yet, so the gateway refuses them with ``task_not_supported``.
TASK_UNITS: dict[TaskType, tuple[UsageUnit, ...]] = {
    TaskType.TEXT: (UsageUnit.TOKENS_INPUT, UsageUnit.TOKENS_OUTPUT),
    TaskType.EMBEDDING: (UsageUnit.TOKENS_INPUT,),
    TaskType.SPEECH: (UsageUnit.AUDIO_MS,),
    TaskType.MULTIMODAL: (UsageUnit.TOKENS_INPUT, UsageUnit.TOKENS_OUTPUT, UsageUnit.IMAGES, UsageUnit.DOCUMENT_PAGES),
}

# Task types an adapter in this release can serve.
IMPLEMENTED_TASKS: frozenset[TaskType] = frozenset({TaskType.TEXT, TaskType.EMBEDDING})
