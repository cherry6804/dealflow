"""Organization-level provider and model selection per AI task (DFR1-015).

A route names a provider key from the registry and a model name. It never stores or reads a credential. A task with no
route is refused by the gateway, so no provider is ever chosen by default.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_gateway.tasks import TaskType
from app.db.models.ai_task_route import AiTaskRoute
from app.db.models.audit_event import AuditEvent
from app.providers.registry import ProviderCategory, get_provider

ROUTE_AUDIT_EVENT = "ai_gateway"
ROUTE_SET_ACTION = "ai_gateway.route.set"
ROUTE_PERMISSION = "governance.capabilities.manage"

# Model names are provider identifiers such as ``gpt-4o-mini`` or ``text-embedding-3-small``. Anything else is refused.
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")


class InvalidRouteError(ValueError):
    """The requested route names an unknown task, an unknown provider, a provider that is not an LLM, or a bad model."""


@dataclass(frozen=True)
class Route:
    provider_key: str
    model: str
    fallback_provider_key: str | None = None
    fallback_model: str | None = None

    def candidates(self) -> tuple[tuple[str, str], ...]:
        """The provider and model pairs to try, in order: the primary, then the fallback when one is set."""
        if self.fallback_provider_key is None or self.fallback_model is None:
            return ((self.provider_key, self.model),)
        return ((self.provider_key, self.model), (self.fallback_provider_key, self.fallback_model))


def resolve_route(db: Session, *, organization_id: uuid.UUID, task: TaskType) -> Route | None:
    row = db.scalar(
        select(AiTaskRoute).where(
            AiTaskRoute.organization_id == organization_id,
            AiTaskRoute.task == task.value,
        )
    )
    if row is None:
        return None
    return Route(
        provider_key=row.provider_key,
        model=row.model,
        fallback_provider_key=row.fallback_provider_key,
        fallback_model=row.fallback_model,
    )


def validate_route(*, provider_key: str, model: str) -> None:
    definition = get_provider(provider_key)
    if definition is None or definition.category is not ProviderCategory.LLM:
        raise InvalidRouteError("The provider is not an AI provider in the registry.")
    if not _MODEL_PATTERN.fullmatch(model):
        raise InvalidRouteError("The model name is not a valid provider model identifier.")


def set_route(
    db: Session,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    task: TaskType,
    provider_key: str,
    model: str,
    fallback_provider_key: str | None = None,
    fallback_model: str | None = None,
) -> AiTaskRoute:
    """Create or replace the route for one task. The change is audited in the same transaction.

    A fallback is optional and must be given with its model. It must differ from the primary pair. The caller holds
    ``governance.capabilities.manage``, which is owner-only, and commits.
    """
    validate_route(provider_key=provider_key, model=model)
    if (fallback_provider_key is None) != (fallback_model is None):
        raise InvalidRouteError("A fallback needs both a provider and a model, or neither.")
    if fallback_provider_key is not None and fallback_model is not None:
        validate_route(provider_key=fallback_provider_key, model=fallback_model)
        if (fallback_provider_key, fallback_model) == (provider_key, model):
            raise InvalidRouteError("The fallback must differ from the primary provider and model.")
    now = datetime.now(UTC)
    row = db.scalar(
        select(AiTaskRoute).where(
            AiTaskRoute.organization_id == organization_id,
            AiTaskRoute.task == task.value,
        )
    )
    previous = None
    if row is None:
        row = AiTaskRoute(
            organization_id=organization_id,
            task=task.value,
            provider_key=provider_key,
            model=model,
            fallback_provider_key=fallback_provider_key,
            fallback_model=fallback_model,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        previous = {
            "provider_key": row.provider_key,
            "model": row.model,
            "fallback_provider_key": row.fallback_provider_key,
            "fallback_model": row.fallback_model,
        }
        row.provider_key = provider_key
        row.model = model
        row.fallback_provider_key = fallback_provider_key
        row.fallback_model = fallback_model
        row.updated_at = now
    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=ROUTE_AUDIT_EVENT,
            action=ROUTE_SET_ACTION,
            decision="allowed",
            outcome=None,
            permission_key=ROUTE_PERMISSION,
            resource_type="ai_task_route",
            resource_id=task.value,
            correlation_id=str(uuid.uuid4()),
            event_metadata=_metadata(
                task=task,
                provider_key=provider_key,
                model=model,
                fallback_provider_key=fallback_provider_key,
                fallback_model=fallback_model,
                previous=previous,
            ),
        )
    )
    db.flush()
    return row


def _metadata(
    *,
    task: TaskType,
    provider_key: str,
    model: str,
    fallback_provider_key: str | None,
    fallback_model: str | None,
    previous: dict[str, str | None] | None,
) -> str:
    payload: dict[str, object] = {
        "task": task.value,
        "provider_key": provider_key,
        "model": model,
        "fallback_provider_key": fallback_provider_key,
        "fallback_model": fallback_model,
    }
    if previous is not None:
        payload["previous"] = previous
    return json.dumps(payload, sort_keys=True)
