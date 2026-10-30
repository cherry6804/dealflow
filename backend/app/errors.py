from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.provider_secrets.redaction import REDACTED, SENSITIVE_FIELD_NAMES


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the standard DealFlow API error response."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }

    if details is not None:
        error["details"] = details

    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=headers,
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """Handle expected HTTP exceptions consistently."""
    detail = exc.detail

    if isinstance(detail, str):
        message = detail
        details = None
    else:
        message = "Request failed."
        details = jsonable_encoder(detail)

    return _error_response(
        status_code=exc.status_code,
        code="HTTP_ERROR",
        message=message,
        details=details,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request validation errors consistently.

    Submitted values of sensitive fields are replaced before they reach the response.
    """
    details = []
    for error in exc.errors():
        location = error.get("loc", ())
        if any(str(part) in SENSITIVE_FIELD_NAMES for part in location):
            error = {**error, "input": REDACTED}
        details.append(error)
    return _error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details=jsonable_encoder(details),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected exceptions without exposing internal details."""
    return _error_response(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred.",
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register centralized DealFlow API exception handlers."""
    app.add_exception_handler(
        HTTPException,
        http_exception_handler,
    )
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    app.add_exception_handler(
        Exception,
        unhandled_exception_handler,
    )
