
"""Application entry point for the DealFlow API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Event, Thread

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.contacts import router as contacts_router
from app.api.customer_profiles import router as customer_profiles_router
from app.api.imports import router as imports_router
from app.api.leads import router as leads_router
from app.api.activities import router as activities_router
from app.api.follow_ups import router as follow_ups_router
from app.api.organizations import router as organizations_router
from app.api.properties import router as properties_router
from app.api.requirements import router as requirements_router
from app.api.site_visits import router as site_visits_router
from app.api.deals import router as deals_router
from app.api.deal_negotiations import router as deal_negotiations_router
from app.api.payment_milestones import router as payment_milestones_router
from app.api.deal_commissions import router as deal_commissions_router
from app.api.referrals import router as referrals_router
from app.api.documents import router as documents_router
from app.api.automation_rules import router as automation_rules_router
from app.api.notifications import router as notifications_router
from app.api.billing_webhooks import router as billing_webhooks_router
from app.api.billing_audit import router as billing_audit_router
from app.auth.email_outbox_worker import run_worker
from app.billing.providers.registry import BillingProviderRegistry
from app.config import get_settings
from app.errors import register_error_handlers
from app.logging import configure_logging

settings = get_settings()
configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and email worker shutdown."""
    stop_event = Event()
    worker_thread = Thread(
        target=run_worker,
        kwargs={"stop_event": stop_event},
        name="dealflow-email-outbox-worker",
        daemon=False,
    )

    logger.info(
        "DealFlow API starting",
        extra={"environment": settings.app_environment},
    )

    worker_thread.start()

    try:
        yield
    finally:
        stop_event.set()
        worker_thread.join(
            timeout=settings.email_outbox_poll_seconds + 10
        )

        if worker_thread.is_alive():
            logger.error(
                "Email outbox worker did not stop within the timeout"
            )

        logger.info("DealFlow API shutting down")


def create_app() -> FastAPI:
    """Create and configure the DealFlow API application."""
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "API for the DealFlow real-estate business platform."
        ),
        lifespan=lifespan,
    )

    application.state.billing_provider_registry = (
        BillingProviderRegistry()
    )

    register_error_handlers(application)

    application.include_router(auth_router)
    application.include_router(organizations_router)
    application.include_router(contacts_router)
    application.include_router(customer_profiles_router)
    application.include_router(leads_router)
    application.include_router(requirements_router)
    application.include_router(properties_router)
    application.include_router(imports_router)
    application.include_router(activities_router)
    application.include_router(follow_ups_router)
    application.include_router(site_visits_router)
    application.include_router(deals_router)
    application.include_router(deal_negotiations_router)
    application.include_router(payment_milestones_router)
    application.include_router(deal_commissions_router)
    application.include_router(referrals_router)
    application.include_router(documents_router)
    application.include_router(automation_rules_router)
    application.include_router(notifications_router)
    application.include_router(billing_webhooks_router)
    application.include_router(billing_audit_router)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Return the API health status."""
        return {
            "service": "dealflow-api",
            "status": "ok",
        }

    logger.info("DealFlow API application initialized")

    return application


app = create_app()
