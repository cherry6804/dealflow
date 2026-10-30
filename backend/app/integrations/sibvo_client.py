"""Typed client for SIBVO's Dealsflo-facing access endpoints.

SIBVO is the authority for identity, access, seats and entitlements. This
module is the only place that calls those endpoints. It applies the timeout,
the single bounded retry for these read-only calls, error normalization and a
correlation ID. Secrets and identity values are never logged.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


class SibvoError(Exception):
    """Base class for failures talking to SIBVO."""


class SibvoUnavailable(SibvoError):
    """SIBVO did not answer in time, could not be reached, or failed server-side."""


class SibvoRejected(SibvoError):
    """SIBVO refused Dealsflo's client credentials. This is a configuration fault."""


class SibvoInvalidResponse(SibvoError):
    """SIBVO answered with a body that does not match the contract."""


@dataclass(frozen=True)
class SibvoSeatUsage:
    """Seat capacity SIBVO reports for the Dealsflo product."""

    organization_id: UUID
    product_key: str
    seat_limit: int | None
    allocated: int
    reserved: int
    available: int | None


def _post_form(settings: Settings, path: str, data: dict[str, str]) -> dict[str, Any]:
    """POST a form to SIBVO with client authentication and a bounded retry.

    Only idempotent read endpoints use this helper, so a retry is always safe.
    """
    secret = settings.sso_dealsflo_client_secret
    if secret is None or not secret.get_secret_value().strip():
        raise SibvoUnavailable("SIBVO client credentials are not configured.")

    url = settings.sso_sibvo_base_url.rstrip("/") + path
    correlation_id = str(uuid.uuid4())

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(
                timeout=settings.sso_http_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    url,
                    data=data,
                    auth=(
                        settings.sso_dealsflo_client_id,
                        secret.get_secret_value(),
                    ),
                    headers={"X-Correlation-ID": correlation_id},
                )
        except (httpx.TimeoutException, httpx.ConnectError):
            logger.warning(
                "SIBVO call failed to connect; retrying if attempts remain",
                extra={"path": path, "attempt": attempt, "correlation_id": correlation_id},
            )
            if attempt == MAX_ATTEMPTS:
                raise SibvoUnavailable("SIBVO could not be reached.") from None
            continue
        except httpx.HTTPError:
            raise SibvoUnavailable("SIBVO call failed.") from None

        if response.status_code == 401:
            logger.error(
                "SIBVO rejected Dealsflo client credentials",
                extra={"path": path, "correlation_id": correlation_id},
            )
            raise SibvoRejected("SIBVO rejected Dealsflo client credentials.")
        if response.status_code >= 500:
            logger.warning(
                "SIBVO returned a server error",
                extra={"path": path, "status": response.status_code, "correlation_id": correlation_id},
            )
            if attempt == MAX_ATTEMPTS:
                raise SibvoUnavailable("SIBVO failed to answer.")
            continue
        if response.status_code >= 400:
            raise SibvoInvalidResponse("SIBVO rejected the request.")

        try:
            body = response.json()
        except ValueError:
            raise SibvoInvalidResponse("SIBVO returned a malformed body.") from None
        if not isinstance(body, dict):
            raise SibvoInvalidResponse("SIBVO returned a non-object body.")
        return body

    raise SibvoUnavailable("SIBVO failed to answer.")


def _parse_seat_usage(
    body: dict[str, Any],
    *,
    organization_id: UUID,
    product_key: str,
) -> SibvoSeatUsage | None:
    """Return seat usage, or None when SIBVO reports no access. Malformed bodies raise."""
    if body.get("active") is not True:
        return None

    if body.get("organization_id") != str(organization_id):
        raise SibvoInvalidResponse("Seat usage is not bound to this organization.")
    if body.get("product_key") != product_key:
        raise SibvoInvalidResponse("Seat usage is not bound to this product.")

    def count(name: str) -> int:
        value = body.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SibvoInvalidResponse(f"Seat field {name} is invalid.")
        return value

    limit = body.get("seat_limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise SibvoInvalidResponse("Seat limit is invalid.")
    available = body.get("available")
    if available is not None and (
        isinstance(available, bool) or not isinstance(available, int) or available < 0
    ):
        raise SibvoInvalidResponse("Seat availability is invalid.")

    return SibvoSeatUsage(
        organization_id=organization_id,
        product_key=product_key,
        seat_limit=limit,
        allocated=count("allocated"),
        reserved=count("reserved"),
        available=available,
    )


def fetch_seat_usage(
    settings: Settings,
    *,
    subject: UUID,
    session_id: UUID,
    organization_id: UUID,
) -> SibvoSeatUsage | None:
    """Return SIBVO's seat usage for an attested session, or None when SIBVO denies it."""
    body = _post_form(
        settings,
        "/sso/seat-usage",
        {
            "subject": str(subject),
            "session_id": str(session_id),
            "organization_id": str(organization_id),
        },
    )
    return _parse_seat_usage(
        body,
        organization_id=organization_id,
        product_key=settings.sso_dealsflo_product_key,
    )


def fetch_introspection(
    settings: Settings,
    *,
    subject: UUID,
    session_id: UUID,
    organization_id: UUID,
) -> dict[str, Any]:
    """Return SIBVO's raw introspection body for a session. Callers validate it."""
    return _post_form(
        settings,
        "/sso/introspect",
        {
            "subject": str(subject),
            "session_id": str(session_id),
            "organization_id": str(organization_id),
        },
    )
