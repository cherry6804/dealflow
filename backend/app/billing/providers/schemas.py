
"""Provider-independent billing data contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BillingRequest(BaseModel):
    """Base for normalized billing requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CheckoutRequest(BillingRequest):
    organization_id: UUID
    subscription_id: UUID
    amount_minor: int = Field(gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    description: str = Field(min_length=1, max_length=500)
    success_url: str
    cancel_url: str
    idempotency_key: str = Field(min_length=1, max_length=200)


class CheckoutSession(BaseModel):
    """Normalized checkout result returned by a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    provider_session_id: str
    checkout_url: str
    expires_at: datetime | None = None


class CustomerRequest(BillingRequest):
    organization_id: UUID
    email: str | None = None
    name: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)


class CustomerReference(BaseModel):
    """Normalized provider-side customer reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    provider_customer_id: str


class RefundRequest(BillingRequest):
    organization_id: UUID
    provider_payment_id: str = Field(min_length=1, max_length=200)
    amount_minor: int | None = Field(default=None, gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class RefundResult(BaseModel):
    """Normalized result of a provider refund operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    provider_refund_id: str
    status: Literal["PENDING", "SUCCEEDED", "FAILED"]
    amount_minor: int
    currency: str


class ProviderCapabilities(BaseModel):
    """Operations a provider implementation explicitly supports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checkout: bool = False
    customer_management: bool = False
    refunds: bool = False
    recurring_billing: bool = False


class VerifiedWebhookEvent(BaseModel):
    """Normalized event returned after successful provider verification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=40)
    provider_event_id: str = Field(min_length=1, max_length=200)
    event_type: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any]
