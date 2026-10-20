
"""Public billing-provider webhook endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.billing.providers.dependencies import (
    get_billing_provider_registry,
    resolve_billing_provider,
)
from app.billing.providers.errors import (
    BillingProviderError,
    ProviderConfigurationError,
    ProviderValidationError,
)
from app.billing.providers.registry import BillingProviderRegistry
from app.billing.webhook_service import ingest_verified_webhook
from app.db.session import get_db_session

router = APIRouter(
    prefix="/api/v1/billing/webhooks",
    tags=["billing-webhooks"],
)


@router.post("/{provider_name}", status_code=202)
async def receive_billing_webhook(
    provider_name: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
    registry: BillingProviderRegistry = Depends(
        get_billing_provider_registry
    ),
) -> dict[str, object]:
    """Verify and durably ingest a provider webhook idempotently."""
    try:
        provider = resolve_billing_provider(registry, provider_name)
    except ProviderConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Billing provider is not configured.",
        ) from exc

    signature = request.headers.get("X-Provider-Signature")
    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing webhook signature.",
        )

    raw_body = await request.body()

    try:
        verified = provider.verify_webhook(raw_body, signature)
    except ProviderValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook signature or payload.",
        ) from exc
    except BillingProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail="Webhook verification is temporarily unavailable.",
        ) from exc

    # Do not allow a provider to authenticate an event under a different
    # provider identity than the endpoint that was called.
    if verified.provider != provider.provider_name:
        raise HTTPException(
            status_code=400,
            detail="Webhook provider identity mismatch.",
        )

    try:
        result = ingest_verified_webhook(db, verified)
        db.commit()
    except Exception:
        db.rollback()
        raise

    response.status_code = 202 if result.created else 200

    return {
        "received": True,
        "duplicate": not result.created,
        "event_id": str(result.event.id),
        "status": result.event.status,
    }
