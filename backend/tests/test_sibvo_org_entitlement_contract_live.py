"""Live cross-repository contract check for the SIBVO organization entitlement snapshot (WS5).

This test calls a real SIBVO instance. It runs only when all of these are set:

- ``SIBVO_LIVE_CONTRACT_URL``: SIBVO API base, for example ``http://localhost:8000/api/v1``
- ``SIBVO_LIVE_CLIENT_SECRET``: the Dealsflo confidential client secret configured in that SIBVO
- ``SIBVO_LIVE_SIGNING_KEY``: the organization snapshot signing key configured in that SIBVO
- ``SIBVO_LIVE_ORGANIZATION_ID``: an organization seeded in that SIBVO with an active Dealsflo subscription

Without them every test is skipped. Skips are reported as "not run", never as passes. Nothing here
fakes a SIBVO response.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.integrations.org_entitlement_snapshot import (
    SibvoDenied,
    VerifiedSnapshot,
    verify_snapshot,
)
from app.integrations.sibvo_client import SibvoRejected, fetch_organization_entitlements

LIVE_URL = os.environ.get("SIBVO_LIVE_CONTRACT_URL")
LIVE_SECRET = os.environ.get("SIBVO_LIVE_CLIENT_SECRET")
LIVE_KEY = os.environ.get("SIBVO_LIVE_SIGNING_KEY")
LIVE_ORG = os.environ.get("SIBVO_LIVE_ORGANIZATION_ID")

pytestmark = pytest.mark.skipif(
    not all([LIVE_URL, LIVE_SECRET, LIVE_KEY, LIVE_ORG]),
    reason="Live SIBVO contract check not configured; this test is not run.",
)


def live_settings():
    return get_settings().model_copy(update={
        "sso_sibvo_base_url": LIVE_URL,
        "sso_dealsflo_client_id": "dealsflo",
        "sso_dealsflo_client_secret": SecretStr(LIVE_SECRET or ""),
        "sso_dealsflo_product_key": "dealsflo",
        "sibvo_org_snapshot_signing_key": SecretStr(LIVE_KEY or ""),
        "sibvo_org_snapshot_key_id": "v1",
    })


def test_live_snapshot_for_the_seeded_organization_verifies() -> None:
    organization_id = UUID(LIVE_ORG or "")
    body = fetch_organization_entitlements(live_settings(), organization_id)
    assert body.get("active") is True, "Seeded organization is expected to have active access."
    verified = verify_snapshot(
        body,
        signing_key=LIVE_KEY,
        key_id="v1",
        organization_id=organization_id,
        product_key="dealsflo",
        now=datetime.now(UTC),
    )
    assert isinstance(verified, VerifiedSnapshot)
    assert [item["feature_key"] for item in verified.snapshot["entitlements"]] == ["ai_gateway"]


def test_live_unknown_organization_is_denied_without_detail() -> None:
    body = fetch_organization_entitlements(live_settings(), uuid4())
    assert body == {"active": False}
    with pytest.raises(SibvoDenied):
        verify_snapshot(
            body,
            signing_key=LIVE_KEY,
            key_id="v1",
            organization_id=uuid4(),
            product_key="dealsflo",
            now=datetime.now(UTC),
        )


def test_live_wrong_client_secret_is_rejected() -> None:
    settings = live_settings().model_copy(update={"sso_dealsflo_client_secret": SecretStr("not-the-secret-value-1234567890")})
    with pytest.raises(SibvoRejected):
        fetch_organization_entitlements(settings, UUID(LIVE_ORG or ""))
