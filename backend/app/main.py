
import logging

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
from app.billing.providers.registry import BillingProviderRegistry
from app.errors import register_error_handlers
from app.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure the DealFlow API application."""
    configure_logging()

    app = FastAPI(
        title="DealFlow API",
        version="0.1.0",
        description="API for the DealFlow real-estate business platform.",
    )

    # Provider registration is explicit. Do not register the fake provider
    # as a production default. Configure real providers in the appropriate
    # deployment initialization when their credentials and adapters exist.
    app.state.billing_provider_registry = BillingProviderRegistry()

    register_error_handlers(app)

    app.include_router(auth_router)
    app.include_router(organizations_router)
    app.include_router(contacts_router)
    app.include_router(customer_profiles_router)
    app.include_router(leads_router)
    app.include_router(requirements_router)
    app.include_router(properties_router)
    app.include_router(imports_router)
    app.include_router(activities_router)
    app.include_router(follow_ups_router)
    app.include_router(site_visits_router)
    app.include_router(deals_router)
    app.include_router(deal_negotiations_router)
    app.include_router(payment_milestones_router)
    app.include_router(deal_commissions_router)
    app.include_router(referrals_router)
    app.include_router(documents_router)
    app.include_router(automation_rules_router)
    app.include_router(notifications_router)
    app.include_router(billing_webhooks_router)
    app.include_router(billing_audit_router)

    logger = logging.getLogger(__name__)
    logger.info("DealFlow API application initialized")

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Return the API health status."""
        return {
            "service": "dealflow-api",
            "status": "ok",
        }

    return app


app = create_app()
