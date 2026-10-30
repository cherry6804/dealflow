"""Cross-repository integration: Dealsflo's SIBVO client against a running SIBVO.

Skipped unless these environment variables are set:

    SIBVO_LIVE_BASE_URL     SIBVO API base URL, for example http://127.0.0.1:8765/api/v1
    SIBVO_LIVE_CLIENT_SECRET  the Dealsflo client secret SIBVO was started with
    SIBVO_LIVE_IDS_JSON     the JSON printed by SIBVO's scripts/seed_e12_integration.py

The checks change SIBVO state (the member's seat is released). Re-run the seed
script before each run. The seed script refuses any database whose name does not
contain "test".
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.integrations import sibvo_client
from app.integrations.sibvo_client import SibvoRejected, SibvoRequestDenied

BASE_URL = os.environ.get("SIBVO_LIVE_BASE_URL", "")
SECRET = os.environ.get("SIBVO_LIVE_CLIENT_SECRET", "")
IDS_PATH = os.environ.get("SIBVO_LIVE_IDS_JSON", "")

pytestmark = pytest.mark.skipif(
    not (BASE_URL and SECRET and IDS_PATH and Path(IDS_PATH).exists()),
    reason="Set SIBVO_LIVE_BASE_URL, SIBVO_LIVE_CLIENT_SECRET and SIBVO_LIVE_IDS_JSON to run.",
)


@pytest.fixture(scope="module")
def ids() -> dict:
    return json.loads(Path(IDS_PATH).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def settings(ids: dict) -> Settings:
    return Settings(
        _env_file=None,
        app_environment="test",
        sso_sibvo_base_url=BASE_URL,
        sso_dealsflo_client_id="dealsflo",
        sso_dealsflo_client_secret=SecretStr(SECRET),
        sso_dealsflo_product_key=ids["product_key"],
        sso_http_timeout_seconds=5.0,
    )


def test_health_reports_a_ready_sibvo(settings: Settings) -> None:
    assert sibvo_client.check_health(settings).status == "ready"


def test_owner_introspection_is_bound_to_the_organization_and_product(settings: Settings, ids: dict) -> None:
    body = sibvo_client.fetch_introspection(
        settings,
        subject=uuid.UUID(ids["owner_subject"]),
        session_id=uuid.UUID(ids["owner_session_id"]),
        organization_id=uuid.UUID(ids["organization_id"]),
    )

    assert body["active"] is True
    assert body["organization_id"] == ids["organization_id"]
    assert body["product_key"] == ids["product_key"]


def test_owner_seat_usage_reflects_sibvo_counts(settings: Settings, ids: dict) -> None:
    usage = sibvo_client.fetch_seat_usage(
        settings,
        subject=uuid.UUID(ids["owner_subject"]),
        session_id=uuid.UUID(ids["owner_session_id"]),
        organization_id=uuid.UUID(ids["organization_id"]),
    )

    assert usage is not None
    assert usage.seat_limit == 3
    assert usage.allocated == 2
    assert usage.reserved == 0
    assert usage.available == 1


def test_wrong_client_secret_is_rejected_not_retried(ids: dict, settings: Settings) -> None:
    wrong = Settings(
        _env_file=None,
        app_environment="test",
        sso_sibvo_base_url=BASE_URL,
        sso_dealsflo_client_id="dealsflo",
        sso_dealsflo_client_secret=SecretStr("not-the-secret"),
        sso_dealsflo_product_key=ids["product_key"],
    )

    with pytest.raises(SibvoRejected):
        sibvo_client.fetch_seat_usage(
            wrong,
            subject=uuid.UUID(ids["owner_subject"]),
            session_id=uuid.UUID(ids["owner_session_id"]),
            organization_id=uuid.UUID(ids["organization_id"]),
        )


def test_removal_releases_the_seat_and_repeating_is_safe(settings: Settings, ids: dict) -> None:
    kwargs = {
        "actor_subject": uuid.UUID(ids["owner_subject"]),
        "actor_session_id": uuid.UUID(ids["owner_session_id"]),
        "organization_id": uuid.UUID(ids["organization_id"]),
        "target_subject": uuid.UUID(ids["member_subject"]),
        "reason": "Integration check",
        "idempotency_key": "integration-removal-0001",
    }

    first = sibvo_client.release_product_seat(settings, **kwargs)
    second = sibvo_client.release_product_seat(settings, **kwargs)

    assert first.released is True and first.already_released is False
    assert second.released is True and second.already_released is True


def test_removed_member_is_denied_and_seat_count_drops(settings: Settings, ids: dict) -> None:
    body = sibvo_client.fetch_introspection(
        settings,
        subject=uuid.UUID(ids["member_subject"]),
        session_id=uuid.UUID(ids["member_session_id"]),
        organization_id=uuid.UUID(ids["organization_id"]),
    )
    usage = sibvo_client.fetch_seat_usage(
        settings,
        subject=uuid.UUID(ids["owner_subject"]),
        session_id=uuid.UUID(ids["owner_session_id"]),
        organization_id=uuid.UUID(ids["organization_id"]),
    )

    assert body == {"active": False}
    assert usage is not None and usage.allocated == 1


def test_an_administrator_cannot_release_their_own_seat(settings: Settings, ids: dict) -> None:
    with pytest.raises(SibvoRequestDenied) as denied:
        sibvo_client.release_product_seat(
            settings,
            actor_subject=uuid.UUID(ids["owner_subject"]),
            actor_session_id=uuid.UUID(ids["owner_session_id"]),
            organization_id=uuid.UUID(ids["organization_id"]),
            target_subject=uuid.UUID(ids["owner_subject"]),
            reason="",
            idempotency_key="integration-removal-owner",
        )
    assert denied.value.status_code == 403
    assert denied.value.error_code == "actor_not_authorized"
