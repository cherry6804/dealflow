"""Redaction for webhook payloads before they are stored, queued or logged (DFR1-012).

Three rules apply, in this order:

1. A field whose name looks like a secret, credential or sensitive identifier has its value replaced, whatever the value is.
2. Email addresses and phone-like numbers inside string values are masked. A phone number keeps only its last four digits, so the
   event can still be matched by a person later without the full number being stored.
3. Long strings are truncated.

The secret-name list reuses ``SENSITIVE_FIELD_NAMES`` from the provider-secrets boundary, and adds the broader names the audit layer
already refuses. Redaction is applied to the parsed payload, never to the raw bytes, which are not stored.
"""

from __future__ import annotations

import re
from typing import Any

from app.provider_secrets.redaction import REDACTED, SENSITIVE_FIELD_NAMES

MAX_STRING_LENGTH = 500
MAX_LIST_ITEMS = 200

_SENSITIVE_KEY = re.compile(
    r"secret|token|passw|api[_-]?key|authoriz|cookie|signature|private|cipher|nonce|plaintext|"
    r"card|cvv|cvc|account[_-]?number|iban|routing|ssn|passport|aadhaar|pan[_-]?number|otp",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s\-()]{6,}\d(?!\w)")
EMAIL_MASK = "[EMAIL]"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_FIELD_NAMES or bool(_SENSITIVE_KEY.search(lowered))


def _mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"***{digits[-4:]}" if len(digits) >= 7 else match.group(0)


def redact_text(value: str) -> str:
    masked = _EMAIL.sub(EMAIL_MASK, value)
    masked = _PHONE.sub(_mask_phone, masked)
    return masked[:MAX_STRING_LENGTH]


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if _is_sensitive_key(str(key)) else redact_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_value(payload)
    if not isinstance(redacted, dict):
        raise TypeError("A payload redacts to an object.")
    return redacted
