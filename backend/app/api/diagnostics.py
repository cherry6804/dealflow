"""Development-only diagnostic for the SIBVO circuit breaker.

Mounted only when SIBVO_DIAGNOSTICS_ENABLED is true, which the settings refuse outside
development and test. Responds 404 when disabled. Accepts only loopback clients. The response
holds breaker counters and timestamps only. It contains no credentials, tokens, tenant data
or request content.
"""

from fastapi import APIRouter, HTTPException, Request, status

from app.config import get_settings
from app.integrations import sibvo_client

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@router.get("/sibvo-circuit")
def sibvo_circuit(request: Request) -> dict:
    if not get_settings().sibvo_diagnostics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    client_host = request.client.host if request.client is not None else ""
    if client_host not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Diagnostics are available locally only.")
    return sibvo_client.breaker.snapshot()
