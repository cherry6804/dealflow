from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create and configure the DealFlow FastAPI application."""
    app = FastAPI(
        title="DealFlow API",
        version="0.1.0",
        description="Backend API for the DealFlow real-estate business platform.",
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Return the current API health status."""
        return {
            "service": "dealflow-api",
            "status": "ok",
        }

    return app


app = create_app()