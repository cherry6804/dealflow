"""Outbox registration for accepted inbound webhook deliveries (DFR1-012)."""

from __future__ import annotations

from app.outbox.service import register_handler
from app.webhooks.service import RECEIVED_EVENT_TYPE, handle_delivery_received


def register_webhook_handlers() -> None:
    """Register the handler for accepted deliveries. Safe to call more than once."""
    register_handler(RECEIVED_EVENT_TYPE, handle_delivery_received)
