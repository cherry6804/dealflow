"""Contract tests for the typed SIBVO client: retries, errors and binding checks."""

import uuid

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.integrations import sibvo_client
from app.integrations.sibvo_client import (
    SibvoInvalidResponse,
    SibvoRejected,
    SibvoUnavailable,
    fetch_seat_usage,
)

ORG = uuid.uuid4()


def make_settings(**overrides) -> Settings:
    values = {
        "app_environment": "test",
        "sso_sibvo_base_url": "http://sibvo.test/api/v1",
        "sso_dealsflo_client_id": "dealsflo",
        "sso_dealsflo_client_secret": SecretStr("client-secret"),
        "sso_dealsflo_product_key": "dealsflo",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class Script:
    """Scripted responses or exceptions, consumed one per POST."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def install(monkeypatch: pytest.MonkeyPatch, script: Script) -> None:
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return script

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sibvo_client.httpx, "Client", FakeClient)


def http_response(status: int, body=None, *, raw: bytes | None = None) -> httpx.Response:
    request = httpx.Request("POST", "http://sibvo.test/api/v1/sso/seat-usage")
    if raw is not None:
        return httpx.Response(status, content=raw, request=request)
    return httpx.Response(status, json=body, request=request)


def bound_body(**overrides) -> dict:
    body = {
        "active": True,
        "organization_id": str(ORG),
        "product_key": "dealsflo",
        "seat_limit": 4,
        "allocated": 2,
        "reserved": 1,
        "available": 1,
    }
    body.update(overrides)
    return body


def call(settings: Settings | None = None):
    return fetch_seat_usage(
        settings or make_settings(),
        subject=uuid.uuid4(),
        session_id=uuid.uuid4(),
        organization_id=ORG,
    )


def test_bound_active_response_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, Script(http_response(200, bound_body())))

    usage = call()

    assert usage is not None
    assert usage.seat_limit == 4
    assert usage.available == 1


def test_inactive_response_is_reported_as_no_access(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, Script(http_response(200, {"active": False})))

    assert call() is None


@pytest.mark.parametrize(
    "override",
    [
        {"organization_id": str(uuid.uuid4())},
        {"product_key": "another-product"},
        {"organization_id": None},
        {"allocated": -1},
        {"allocated": True},
        {"reserved": "2"},
        {"seat_limit": -3},
        {"available": 1.5},
    ],
    ids=[
        "other-organization",
        "other-product",
        "unbound-organization",
        "negative-allocated",
        "boolean-allocated",
        "string-reserved",
        "negative-limit",
        "fractional-available",
    ],
)
def test_bindings_and_shapes_are_enforced(monkeypatch: pytest.MonkeyPatch, override: dict) -> None:
    install(monkeypatch, Script(http_response(200, bound_body(**override))))

    with pytest.raises(SibvoInvalidResponse):
        call()


def test_one_connection_failure_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(httpx.ConnectError("reset"), http_response(200, bound_body()))
    install(monkeypatch, script)

    usage = call()

    assert usage is not None
    assert script.calls == 2


def test_persistent_connection_failure_is_bounded_and_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(httpx.ConnectError("down"), httpx.ConnectError("down"), http_response(200, bound_body()))
    install(monkeypatch, script)

    with pytest.raises(SibvoUnavailable):
        call()
    assert script.calls == 2


def test_timeout_is_treated_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"))
    install(monkeypatch, script)

    with pytest.raises(SibvoUnavailable):
        call()
    assert script.calls == 2


def test_server_error_is_retried_then_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(http_response(503, {"detail": "busy"}), http_response(500, {"detail": "boom"}))
    install(monkeypatch, script)

    with pytest.raises(SibvoUnavailable):
        call()
    assert script.calls == 2


def test_rejected_client_credentials_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(http_response(401, {"detail": "no"}), http_response(200, bound_body()))
    install(monkeypatch, script)

    with pytest.raises(SibvoRejected):
        call()
    assert script.calls == 1


def test_client_error_is_normalized_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script(http_response(403, {"detail": "forbidden"}))
    install(monkeypatch, script)

    with pytest.raises(SibvoInvalidResponse):
        call()
    assert script.calls == 1


def test_malformed_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, Script(http_response(200, raw=b"not json")))

    with pytest.raises(SibvoInvalidResponse):
        call()


def test_missing_credentials_fail_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    script = Script()
    install(monkeypatch, script)

    with pytest.raises(SibvoUnavailable):
        call(make_settings(sso_dealsflo_client_secret=None))
    assert script.calls == 0
