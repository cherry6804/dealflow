from fastapi import FastAPI

from app.errors import register_error_handlers


def create_app() -> FastAPI:
    """Create and configure the DealFlow API application."""
    app = FastAPI(
        title="DealFlow API",
        version="0.1.0",
        description="API for the DealFlow real-estate business platform.",
    )

    register_error_handlers(app)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Return the API health status."""
        return {
            "service": "dealflow-api",
            "status": "ok",
        }

    return app


app = create_app()