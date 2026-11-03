"""The authenticated principal for the current request, carried to audit attribution (WS6 WP3).

Identity is established once, by the authentication layer:

- ``get_current_user_context`` authenticates the session cookie and yields the user.
- ``get_tenant_context`` binds the request's organization to that session and requires an active membership.
  It then calls ``issue_principal`` and binds the result for the duration of the request with
  ``bound_principal``.

Audit attribution is derived from this bound principal. A caller cannot construct a principal, because the
constructor requires a token that only this module holds, and it cannot bind one, because ``issue_principal``
is called from the authentication layer alone (enforced by a test that scans the source tree).

The binding is a context variable set by an async generator dependency. That is the form FastAPI keeps
visible to both synchronous and asynchronous endpoints. A value set in a synchronous dependency is not
visible to the endpoint, which is why the binding is not made there.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

_ISSUED = object()
_current: ContextVar[TrustedPrincipal | None] = ContextVar("audit_principal", default=None)


@dataclass(frozen=True)
class TrustedPrincipal:
    """The authenticated user and the organization the request is bound to."""

    user_id: UUID
    organization_id: UUID
    _issued: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issued is not _ISSUED:
            raise TypeError("A TrustedPrincipal is issued only by the authentication layer.")


def issue_principal(*, user_id: UUID, organization_id: UUID) -> TrustedPrincipal:
    """Issue a principal for an authenticated request. Called by the tenant dependency only."""
    return TrustedPrincipal(user_id=user_id, organization_id=organization_id, _issued=_ISSUED)


@contextmanager
def bound_principal(principal: TrustedPrincipal) -> Iterator[TrustedPrincipal]:
    """Bind ``principal`` for the enclosed work. The previous binding is restored on exit."""
    token = _current.set(principal)
    try:
        yield principal
    finally:
        _current.reset(token)


def current_principal() -> TrustedPrincipal | None:
    """The principal bound for this request or operation, or None when there is none."""
    return _current.get()
