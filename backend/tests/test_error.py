from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.main import create_app


class Payload(BaseModel):
    name: str


def test_http_exception_uses_standard_error_response() -> None:
    app = create_app()

    @app.get("/not-found")
    async def not_found() -> None:
        raise HTTPException(
            status_code=404,
            detail="Resource not found",
        )

    client = TestClient(app)

    response = client.get("/not-found")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Resource not found",
        }
    }


def test_validation_exception_uses_standard_error_response() -> None:
    app = create_app()

    @app.post("/payload")
    async def create_payload(payload: Payload) -> Payload:
        return payload

    client = TestClient(app)

    response = client.post("/payload", json={})

    assert response.status_code == 422

    body = response.json()

    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed."
    assert "details" in body["error"]


def test_unhandled_exception_does_not_expose_internal_details() -> None:
    app = create_app()

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal implementation detail")

    client = TestClient(
        app,
        raise_server_exceptions=False,
    )

    response = client.get("/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
        }
    }