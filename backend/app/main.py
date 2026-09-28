import logging

from fastapi import FastAPI

from app.api.auth import router as auth_router
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

    register_error_handlers(app)

    app.include_router(auth_router)

    logger = logging.getLogger(__name__)
    logger.info("DealFlow API application initialized")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Return the API health status."""
        return {
            "service": "dealflow-api",
            "status": "ok",
        }

    return app


app = create_app()