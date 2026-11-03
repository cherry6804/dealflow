"""Redaction helpers for provider secrets."""

from __future__ import annotations

REDACTED = "[REDACTED]"

# Request field names whose submitted values must never be echoed in validation errors.
SENSITIVE_FIELD_NAMES = frozenset({"secret", "secret_value", "api_key", "password", "token"})


class ProviderSecret:
    """A provider secret held for one backend provider call.

    The value is reachable only through ``reveal``. Representation, string conversion and
    pickling are refused, so the secret cannot reach logs, responses or serialized state by
    accident.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the secret for a provider adapter call. Do not log or return it."""
        return self._value

    def __repr__(self) -> str:
        return f"ProviderSecret({REDACTED})"

    __str__ = __repr__

    def __reduce__(self) -> str:
        raise TypeError("ProviderSecret cannot be serialized.")
