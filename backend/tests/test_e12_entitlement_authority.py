"""DFR1-005: SIBVO is the entitlement authority outside development and test."""

from collections.abc import Iterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.auth.dependencies import CurrentUserContext
from app.billing.entitlements import _feature_enabled
from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_cached_settings() -> Iterator[None]:
    """Drop the cached settings after each test, once monkeypatch restores the env."""
    yield
    get_settings.cache_clear()


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _use_fallback_flag(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("LOCAL_ENTITLEMENT_FALLBACK_ENABLED", value)
    get_settings.cache_clear()


def _attested_context(
    organization_id: object,
    *,
    session_organization_id: object | None = None,
) -> CurrentUserContext:
    return CurrentUserContext(
        user=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        session_organization_id=session_organization_id or organization_id,  # type: ignore[arg-type]
        sibvo_attested=True,
        sibvo_access={
            "entitlements": [
                {"feature_key": "automation", "enabled": True, "limit_value": None, "limit_unit": None}
            ]
        },
    )


def test_fallback_is_off_by_default() -> None:
    # The test process enables the flag through conftest, so check the field default.
    assert Settings.model_fields["local_entitlement_fallback_enabled"].default is False


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_fallback_flag_stops_startup_outside_development_and_test(environment: str) -> None:
    with pytest.raises(ValidationError, match="Local entitlement fallback is allowed only"):
        _settings(app_environment=environment, local_entitlement_fallback_enabled=True)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_fallback_flag_is_allowed_in_development_and_test(environment: str) -> None:
    settings = _settings(app_environment=environment, local_entitlement_fallback_enabled=True)
    assert settings.local_entitlement_fallback_enabled is True


def test_unattested_session_is_denied_when_fallback_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_fallback_flag(monkeypatch, "false")
    unattested = CurrentUserContext(user=SimpleNamespace(id=uuid4()))  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as denied:
        _feature_enabled(
            None,  # type: ignore[arg-type]
            user_context=unattested,
            organization_id=uuid4(),
            key="automation",
        )

    assert denied.value.status_code == 403
    get_settings.cache_clear()


def test_attested_snapshot_authorizes_only_its_own_organization() -> None:
    organization_id = uuid4()
    context = _attested_context(organization_id)

    assert _feature_enabled(
        None,  # type: ignore[arg-type]
        user_context=context,
        organization_id=organization_id,
        key="automation",
    ) is True

    with pytest.raises(HTTPException) as other_tenant:
        _feature_enabled(
            None,  # type: ignore[arg-type]
            user_context=context,
            organization_id=uuid4(),
            key="automation",
        )
    assert other_tenant.value.status_code == 403


def test_attested_snapshot_from_another_session_organization_is_denied() -> None:
    organization_id = uuid4()
    context = _attested_context(organization_id, session_organization_id=uuid4())

    with pytest.raises(HTTPException) as mismatched:
        _feature_enabled(
            None,  # type: ignore[arg-type]
            user_context=context,
            organization_id=organization_id,
            key="automation",
        )
    assert mismatched.value.status_code == 403
