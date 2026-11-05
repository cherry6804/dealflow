"""Signature verifier contract for inbound webhooks (DFR1-012).

A verifier decides whether one delivery was signed with the endpoint's secret and whether its timestamp is inside the replay window.
It never reads the database, never parses the body and never decides what the event means. Only a verified delivery is parsed and
processed.

Provider-specific verifiers belong to provider adapters and are added with DFR1-007. This module provides the neutral contract and one
verifier, ``hmac_sha256_v1``. That verifier is Dealsflo's own synthetic format, documented in ``docs/architecture``. It is not
compatible with any provider's signature scheme, and a passing test does not show that any provider accepts it.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from app.provider_secrets.redaction import ProviderSecret

SIGNATURE_PREFIX = "sha256="
MAX_CLOCK_SKEW_SECONDS = 60
MAX_SIGNATURE_LENGTH = 80
MAX_TIMESTAMP_LENGTH = 20

REASON_MISSING_SIGNATURE = "missing_signature"
REASON_MALFORMED_SIGNATURE = "malformed_signature"
REASON_INVALID_SIGNATURE = "invalid_signature"
REASON_MISSING_TIMESTAMP = "missing_timestamp"
REASON_MALFORMED_TIMESTAMP = "malformed_timestamp"
REASON_STALE_TIMESTAMP = "stale_timestamp"
REASON_FUTURE_TIMESTAMP = "future_timestamp"


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    reason: str | None = None

    @classmethod
    def accept(cls) -> VerificationResult:
        return cls(verified=True)

    @classmethod
    def refuse(cls, reason: str) -> VerificationResult:
        return cls(verified=False, reason=reason)


class SignatureVerifier(Protocol):
    """What every verifier provides. ``key`` is stored on the endpoint and selects the verifier at ingress."""

    key: str

    def verify(
        self,
        *,
        secret: ProviderSecret,
        timestamp_header: str | None,
        signature_header: str | None,
        body: bytes,
        now_epoch: int,
        replay_window_seconds: int,
    ) -> VerificationResult: ...


class HmacSha256Verifier:
    """Dealsflo synthetic format ``hmac_sha256_v1``.

    The sender computes HMAC-SHA256 over the ASCII bytes of ``<timestamp>.`` followed by the exact raw body, with the endpoint secret as
    the key, and sends ``X-Dealsflo-Signature: sha256=<hex>`` and ``X-Dealsflo-Timestamp: <unix seconds>``.

    The signature is checked before the timestamp's age, so a stale but correctly signed delivery is reported as stale and a forged one
    as invalid. Comparison is constant time.
    """

    key = "hmac_sha256_v1"

    def verify(
        self,
        *,
        secret: ProviderSecret,
        timestamp_header: str | None,
        signature_header: str | None,
        body: bytes,
        now_epoch: int,
        replay_window_seconds: int,
    ) -> VerificationResult:
        if not signature_header:
            return VerificationResult.refuse(REASON_MISSING_SIGNATURE)
        if len(
            signature_header
        ) > MAX_SIGNATURE_LENGTH or not signature_header.startswith(SIGNATURE_PREFIX):
            return VerificationResult.refuse(REASON_MALFORMED_SIGNATURE)
        if not timestamp_header:
            return VerificationResult.refuse(REASON_MISSING_TIMESTAMP)
        timestamp = _parse_timestamp(timestamp_header)
        if timestamp is None:
            return VerificationResult.refuse(REASON_MALFORMED_TIMESTAMP)

        expected = hmac.new(
            secret.reveal().encode("utf-8"),
            f"{timestamp}.".encode("ascii") + body,
            hashlib.sha256,
        ).hexdigest()
        presented = signature_header[len(SIGNATURE_PREFIX) :]
        if not hmac.compare_digest(
            expected.encode("ascii"), presented.encode("ascii", errors="replace")
        ):
            return VerificationResult.refuse(REASON_INVALID_SIGNATURE)

        if timestamp > now_epoch + MAX_CLOCK_SKEW_SECONDS:
            return VerificationResult.refuse(REASON_FUTURE_TIMESTAMP)
        if now_epoch - timestamp > replay_window_seconds:
            return VerificationResult.refuse(REASON_STALE_TIMESTAMP)
        return VerificationResult.accept()


def _parse_timestamp(value: str) -> int | None:
    if len(value) > MAX_TIMESTAMP_LENGTH or not value.isdigit():
        return None
    return int(value)


VERIFIERS: dict[str, SignatureVerifier] = {HmacSha256Verifier.key: HmacSha256Verifier()}


def get_verifier(key: str) -> SignatureVerifier | None:
    return VERIFIERS.get(key)
