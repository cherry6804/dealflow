"""Structured HTTP responses for rate-limit decisions.

Uses the application's error envelope: ``{"error": {"code", "message", "details"}}``. A rate-limited
request gets 429 with ``Retry-After``. A request denied because the limiter is unavailable gets 503,
which tells the client to retry later without implying that it exceeded a limit.
"""

from __future__ import annotations

from fastapi import status
from fastapi.responses import JSONResponse

from app.rate_limits.limiter import REASON_RATE_LIMITED, RateLimitDecision


def rate_limit_error_response(decision: RateLimitDecision) -> JSONResponse:
    if decision.allowed:
        raise ValueError("An allowed decision has no error response.")

    if decision.reason_code == REASON_RATE_LIMITED:
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        code = "RATE_LIMITED"
        message = "Too many requests. Try again after the retry period."
        headers = {"Retry-After": str(decision.retry_after_seconds)}
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        code = "RATE_LIMIT_UNAVAILABLE"
        message = "Rate limiting is temporarily unavailable. Try again later."
        headers = {"Retry-After": "30"}

    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": {
                    "execution_type": decision.execution_type,
                    "scope": decision.scope,
                    "limit": decision.limit,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            }
        },
    )
