"""AI API namespace parity: canonical and legacy mounts behave identically (E06 WS2, ADR-0031).

Every governance and provider-credential route is served under ``/api/v1/ai`` (canonical) and under
its previous path (legacy). For each route and actor, both mounts must return the same status and
normalized body, record the same number of audit events, and invoke the same handler. Each mount
runs against its own organization, so mutations never share state or double-count side effects.
"""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.api.governance import canonical_router as canonical_governance_router
from app.api.governance import governance_routes
from app.api.governance import router as legacy_governance_router
from app.api.provider_credentials import canonical_router as canonical_provider_router
from app.api.provider_credentials import provider_credential_routes
from app.api.provider_credentials import router as legacy_provider_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.permission import Permission
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest, RetentionPolicy
from app.db.models.provider_credential import ProviderCredential
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.session import SessionLocal, get_db_session
from tests.test_deals_api import create_membership, create_user
from tests.test_team_api import (
    TestingSessionLocal,
    attach_role,
    create_owner_manager,
    create_role,
)

API_PREFIX = "/api/v1/"
CANONICAL_PREFIX = "/api/v1/ai/"
ORGANIZATION_HEADER = "X-Organization-ID"
ACTORS = ("owner", "admin", "member", "custom_role", "cross_tenant", "unauthenticated")
ROUTER_PAIRS = {
    "canonical": (canonical_governance_router, canonical_provider_router),
    "legacy": (legacy_governance_router, legacy_provider_router),
}
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")


@dataclass(frozen=True)
class RouteCase:
    """One of the 18 routes, described by its legacy path."""

    name: str
    method: str
    legacy_path: str
    permission: str | None
    owner_only: bool
    success: int
    body: dict[str, object] | None = None
    tenant_only: bool = False
    prerequisite: str | None = None


ROUTES: tuple[RouteCase, ...] = (
    RouteCase("capabilities.list", "GET", "/api/v1/governance/capabilities",
              "governance.capabilities.read", False, 200),
    RouteCase("capabilities.update", "PATCH", "/api/v1/governance/capabilities/automation.master",
              "governance.capabilities.manage", True, 200,
              body={"is_enabled": True, "confirm": True}),
    RouteCase("usage.budgets.list", "GET", "/api/v1/governance/usage/budgets",
              "governance.usage.read", False, 200),
    RouteCase("usage.budgets.update", "PUT", "/api/v1/governance/usage/budgets/tokens_input",
              "governance.budgets.manage", True, 200,
              body={"limit_quantity": 1000, "confirm": True}),
    RouteCase("privacy.categories.list", "GET", "/api/v1/governance/privacy/categories",
              "governance.privacy.read", False, 200),
    RouteCase("privacy.retention.list", "GET", "/api/v1/governance/privacy/retention",
              "governance.privacy.read", False, 200),
    RouteCase("privacy.retention.update", "PUT", "/api/v1/governance/privacy/retention/crm.leads",
              "governance.privacy.manage", True, 200,
              body={"retention_days": 90, "confirm": True}),
    RouteCase("privacy.legal_holds.create", "POST", "/api/v1/governance/privacy/legal-holds",
              "governance.privacy.manage", True, 201,
              body={"category_key": "crm.contacts", "reason": "Parity check", "confirm": True}),
    RouteCase("privacy.legal_holds.release", "POST",
              "/api/v1/governance/privacy/legal-holds/{hold_id}/release",
              "governance.privacy.manage", True, 200, prerequisite="legal_hold"),
    RouteCase("privacy.legal_holds.list", "GET", "/api/v1/governance/privacy/legal-holds",
              "governance.privacy.read", False, 200),
    RouteCase("privacy.requests.list", "GET", "/api/v1/governance/privacy/requests",
              "governance.privacy.read", False, 200),
    RouteCase("privacy.requests.create", "POST", "/api/v1/governance/privacy/requests",
              "governance.privacy.manage", True, 201,
              body={"request_type": "export", "categories": ["crm.contacts"], "confirm": True}),
    RouteCase("privacy.requests.cancel", "POST",
              "/api/v1/governance/privacy/requests/{request_id}/cancel",
              "governance.privacy.manage", True, 200, prerequisite="privacy_request"),
    RouteCase("governance.access", "GET", "/api/v1/governance/access",
              None, False, 200, tenant_only=True),
    RouteCase("provider_credentials.list", "GET", "/api/v1/provider-credentials",
              "provider_credentials.read", False, 200),
    RouteCase("provider_credentials.create", "POST", "/api/v1/provider-credentials",
              "provider_credentials.manage", True, 201,
              body={"provider_key": "openai", "label": "Parity", "secret": "sk-parity-create"}),
    RouteCase("provider_credentials.rotate", "POST",
              "/api/v1/provider-credentials/{credential_id}/rotate",
              "provider_credentials.manage", True, 200,
              body={"secret": "sk-parity-rotate"}, prerequisite="credential"),
    RouteCase("provider_credentials.revoke", "POST",
              "/api/v1/provider-credentials/{credential_id}/revoke",
              "provider_credentials.manage", True, 200, prerequisite="credential"),
)


def expected_status(route: RouteCase, actor: str) -> int:
    """Status a correct authorization layer returns for this route and actor."""
    if actor == "unauthenticated":
        return 401
    if actor == "cross_tenant":
        return 403
    if route.tenant_only:
        return route.success
    if actor == "member":
        return 403
    if route.owner_only and actor != "owner":
        return 403
    return route.success


def _canonical(path: str) -> str:
    return path.replace(API_PREFIX, CANONICAL_PREFIX, 1)


PATH_PARAMETER_VALUES = {
    "automation.master": "capability_key",
    "tokens_input": "unit",
    "crm.leads": "category_key",
}


def _template(path: str) -> str:
    """Return the route template FastAPI registers, replacing example values with parameter names."""
    for value, name in PATH_PARAMETER_VALUES.items():
        path = path.replace(f"/{value}", f"/{{{name}}}")
    return path


def _mount_path(route: RouteCase, mount: str) -> str:
    return route.legacy_path if mount == "legacy" else _canonical(route.legacy_path)


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


@pytest.fixture(autouse=True)
def provider_keyring(monkeypatch) -> Iterator[None]:
    """Configure a local test keyring so provider create and rotate can encrypt."""
    monkeypatch.setenv("PROVIDER_SECRETS_ACTIVE_KEY_ID", "parity-v1")
    monkeypatch.setenv("PROVIDER_SECRETS_KEYRING", json.dumps({"parity-v1": _key()}))
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def created_organizations() -> Iterator[list[uuid.UUID]]:
    """Track every organization a test creates, then remove the rows the routes wrote."""
    organizations: list[uuid.UUID] = []
    yield organizations
    with SessionLocal() as db:
        for organization_id in organizations:
            for model in (
                PrivacyDataRequest,
                LegalHold,
                RetentionPolicy,
                OrganizationUsageBudget,
                OrganizationCapabilitySetting,
                ProviderCredential,
                AuditEvent,
            ):
                db.execute(delete(model).where(model.organization_id == organization_id))
        db.commit()


def _permission_id(db, key: str) -> uuid.UUID:
    permission = db.scalar(select(Permission).where(Permission.key == key))
    if permission is None:
        permission = Permission(key=key, is_active=True)
        db.add(permission)
        db.flush()
    return permission.id


def _member_with_role(organization, *, role_name: str | None, permission: str | None):
    """Add a user to the organization with a default role, or with a custom role holding one key."""
    db = TestingSessionLocal()
    try:
        user = create_user(db)
        membership = create_membership(db, user=user, organization=organization)
        if role_name is not None:
            role = db.scalar(
                select(Role).where(Role.organization_id == organization.id, Role.name == role_name)
            )
            assert role is not None, f"default role {role_name!r} was not provisioned"
        else:
            role = create_role(db, organization_id=organization.id, name=f"Parity {uuid.uuid4()}")
            if permission is not None:
                db.add(RolePermission(role_id=role.id, permission_id=_permission_id(db, permission)))
        attach_role(db, membership=membership, role=role)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def _seed(actor: str, route: RouteCase, created_organizations: list[uuid.UUID]):
    """Return (request user or None, organization id, owner used for prerequisites)."""
    owner, organization = create_owner_manager(permissions=())
    created_organizations.append(organization.id)
    if actor == "owner":
        return owner, organization.id, owner
    if actor == "unauthenticated":
        return None, organization.id, owner
    if actor == "cross_tenant":
        outsider, outsider_organization = create_owner_manager(permissions=())
        created_organizations.append(outsider_organization.id)
        return outsider, organization.id, owner
    if actor == "admin":
        user = _member_with_role(organization, role_name="Admin", permission=None)
    elif actor == "member":
        user = _member_with_role(organization, role_name="Member", permission=None)
    else:
        user = _member_with_role(organization, role_name=None, permission=route.permission)
    return user, organization.id, owner


def _app(mount: str, user) -> FastAPI:
    """Build an app that mounts one side of the namespace, with the real dependencies except auth."""
    app = FastAPI()
    for router in ROUTER_PAIRS[mount]:
        app.include_router(router)

    def override_get_db_session() -> Iterator:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    if user is not None:
        app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    return app


def _prepare(kind: str, owner, organization_id: uuid.UUID) -> dict[str, str]:
    """Create the prerequisite through the owner's canonical route, outside the measured call."""
    with TestClient(_app("canonical", owner)) as client:
        client.headers.update({ORGANIZATION_HEADER: str(organization_id)})
        if kind == "legal_hold":
            response = client.post(
                _canonical("/api/v1/governance/privacy/legal-holds"),
                json={"category_key": "crm.contacts", "reason": "Parity setup", "confirm": True},
            )
            key = "hold_id"
        elif kind == "privacy_request":
            response = client.post(
                _canonical("/api/v1/governance/privacy/requests"),
                json={"request_type": "export", "categories": ["crm.contacts"], "confirm": True},
            )
            key = "request_id"
        elif kind == "credential":
            response = client.post(
                _canonical("/api/v1/provider-credentials"),
                json={"provider_key": "openai", "label": "Parity setup", "secret": "sk-parity-setup"},
            )
            key = "credential_id"
        else:
            raise AssertionError(f"unknown prerequisite {kind!r}")
    assert response.status_code == 201, response.text
    return {key: str(response.json()["id"])}


def _audit_count(organization_id: uuid.UUID) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.organization_id == organization_id)
        ) or 0


def _normalize(text: str) -> object:
    """Replace identifiers and timestamps, which differ between the two isolated organizations."""
    normalized = TIMESTAMP_PATTERN.sub("<timestamp>", UUID_PATTERN.sub("<uuid>", text))
    return json.loads(normalized)


def _send(route: RouteCase, mount: str, actor: str, created_organizations: list[uuid.UUID]) -> dict[str, object]:
    """Run one request on one mount in its own organization and summarize the outcome."""
    user, organization_id, owner = _seed(actor, route, created_organizations)
    ids: dict[str, str] = {}
    if route.prerequisite is not None:
        ids = _prepare(route.prerequisite, owner, organization_id)

    before = _audit_count(organization_id)
    path = _mount_path(route, mount).format(**ids)
    with TestClient(_app(mount, user), raise_server_exceptions=False) as client:
        client.headers.update({ORGANIZATION_HEADER: str(organization_id)})
        response = client.request(route.method, path, json=route.body)
    after = _audit_count(organization_id)

    return {
        "status": response.status_code,
        "body": _normalize(response.text),
        "audit_events_written": after - before,
    }


ROUTE_IDS = [route.name for route in ROUTES]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", ROUTES, ids=ROUTE_IDS)
def test_canonical_and_legacy_mounts_behave_identically(
    route: RouteCase, actor: str, created_organizations: list[uuid.UUID]
) -> None:
    canonical = _send(route, "canonical", actor, created_organizations)
    legacy = _send(route, "legacy", actor, created_organizations)

    assert canonical["status"] == expected_status(route, actor), canonical
    assert legacy == canonical


def test_shared_handler_routers_define_all_eighteen_routes() -> None:
    """The handler set itself must define exactly the 18 documented routes, under their prefixes."""
    definitions = (
        ("/api/v1/governance", governance_routes),
        ("/api/v1/provider-credentials", provider_credential_routes),
    )
    actual = sorted(
        (f"{prefix}{route.path}", method)
        for prefix, router in definitions
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    )
    expected = sorted((_template(route.legacy_path), route.method) for route in ROUTES)
    assert actual == expected


def test_both_mounts_include_the_same_handler_router() -> None:
    """Both mounts must be built from one handler router, so no handler can diverge (ADR-0031).

    FastAPI keeps each included router as a wrapper whose ``original_router`` names its source.
    """
    pairs = (
        (canonical_governance_router, legacy_governance_router, governance_routes),
        (canonical_provider_router, legacy_provider_router, provider_credential_routes),
    )
    for canonical, legacy, shared in pairs:
        assert [route.original_router for route in canonical.routes] == [shared]
        assert [route.original_router for route in legacy.routes] == [shared]


def test_openapi_lists_canonical_routes_and_hides_legacy_routes() -> None:
    from app.main import app as application

    paths = application.openapi()["paths"]
    for route in ROUTES:
        canonical_path = _canonical(_template(route.legacy_path))
        assert canonical_path in paths, canonical_path
        assert route.method.lower() in paths[canonical_path], canonical_path
        assert route.legacy_path not in paths, route.legacy_path
        assert _template(route.legacy_path) not in paths, route.legacy_path
