import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import import_key
from pydantic import SecretStr

from app.api import auth as auth_api
from app.api import sso
from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def client(monkeypatch):
    """Use a fake database and avoid starting application background workers."""
    subject_id = uuid4()
    sibvo_org_id = uuid4()
    user_id = uuid4()
    dealsflo_org_id = uuid4()

    user = SimpleNamespace(
        id=user_id,
        is_active=True,
        is_email_verified=True,
    )
    organization = SimpleNamespace(
        id=dealsflo_org_id,
        is_active=True,
    )
    membership = SimpleNamespace(is_active=True)

    identity_link = SimpleNamespace(
        dealsflo_user_id=user_id,
    )
    organization_link = SimpleNamespace(
        dealsflo_organization_id=dealsflo_org_id,
    )

    db = SimpleNamespace()
    db.commit = lambda: None
    db.rollback = lambda: None

    def fake_scalar(statement):
        query = str(statement)
        if "sibvo_identity_links" in query:
            return identity_link
        if "sibvo_organization_links" in query:
            return organization_link
        return membership

    def fake_get(model, key):
        if key == user_id:
            return user
        if key == dealsflo_org_id:
            return organization
        return None

    db.scalar = fake_scalar
    db.get = fake_get

    def override_db_session():
        yield db

    app.dependency_overrides[get_db_session] = override_db_session

    # Do not use TestClient as a context manager: entering its context
    # starts the app lifespan, including the email-outbox worker.
    test_client = TestClient(app)

    data = {
        "db": db,
        "subject_id": subject_id,
        "sibvo_org_id": sibvo_org_id,
        "user_id": user_id,
        "dealsflo_org_id": dealsflo_org_id,
        "user": user,
        "organization": organization,
        "identity_link": identity_link,
        "organization_link": organization_link,
        "membership": membership,
    }

    # Store test data separately rather than relying on TestClient.state.
    test_client.sso_test_data = data

    yield test_client

    app.dependency_overrides.pop(get_db_session, None)
    test_client.close()


def configure_sso(monkeypatch):
    settings = sso.get_settings().model_copy(
        update={
            "sso_dealsflo_client_secret": SecretStr("test-secret"),
            "sso_sibvo_base_url": "http://localhost:8000/api/v1",
        }
    )
    monkeypatch.setattr(sso, "get_settings", lambda: settings)


def set_flow_cookie(client, state="test-state-1234567890"):
    settings = sso.get_settings()
    client.cookies.set(
        settings.sso_flow_cookie_name,
        json.dumps(
            {
                "state": state,
                "verifier": "test-verifier",
                "nonce": "test-nonce-1234567890",
            }
        ),
        path=settings.sso_flow_cookie_path,
    )
    return state


def mock_token_exchange(monkeypatch, claims, *, publish_wrong_key=False):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    id_token = jwt.encode(
        {"alg": "RS256", "kid": "test-key", "typ": "JWT"},
        claims,
        import_key(private_pem, "RSA", {"kid": "test-key"}),
        algorithms=["RS256"],
    )
    public_key = import_key(
        public_pem,
        "RSA",
        {"kid": "test-key", "use": "sig", "alg": "RS256"},
    )
    if publish_wrong_key:
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = import_key(
            wrong_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
            "RSA",
            {"kid": "test-key", "use": "sig", "alg": "RS256"},
        )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": id_token}

    class FakeJwksResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"keys": [public_key.as_dict(private=False)]}

    class FakeHttpClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

        def get(self, *args, **kwargs):
            return FakeJwksResponse()

    monkeypatch.setattr(sso.httpx, "Client", FakeHttpClient)


def valid_claims(client):
    data = client.sso_test_data
    return {
        "iss": "http://localhost:8000/api/v1",
        "aud": "dealsflo",
        "sub": str(data["subject_id"]),
        "sid": str(uuid4()),
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": "test-nonce-1234567890",
        "organization_id": str(data["sibvo_org_id"]),
        "email": "user@example.com",
        "email_verified": True,
        "name": "Test User",
        "organization_name": "Test Workspace",
        "organization_role": "member",
    }


def test_start_requires_sso_client_secret(client, monkeypatch):
    settings = sso.get_settings().model_copy(
        update={"sso_dealsflo_client_secret": None}
    )
    monkeypatch.setattr(sso, "get_settings", lambda: settings)

    response = client.get(f"/api/v1/sso/start?organization_id={uuid4()}")

    assert response.status_code == 503


def test_callback_rejects_missing_flow_cookie(client, monkeypatch):
    configure_sso(monkeypatch)

    response = client.post(
        "/api/v1/sso/callback",
        json={
            "code": "a" * 32,
            "state": "test-state-1234567890",
        },
    )

    assert response.status_code == 400


def test_callback_rejects_state_mismatch(client, monkeypatch):
    configure_sso(monkeypatch)
    set_flow_cookie(client)

    response = client.post(
        "/api/v1/sso/callback",
        json={
            "code": "a" * 32,
            "state": "wrong-state-123456789",
        },
    )

    assert response.status_code == 400
    assert "state validation failed" in response.text.lower()


def test_callback_rejects_invalid_issuer(client, monkeypatch):
    configure_sso(monkeypatch)
    set_flow_cookie(client)

    claims = valid_claims(client)
    claims["iss"] = "https://attacker.example"
    mock_token_exchange(monkeypatch, claims)

    response = client.post(
        "/api/v1/sso/callback",
        json={
            "code": "a" * 32,
            "state": "test-state-1234567890",
        },
    )

    assert response.status_code == 502


def test_callback_rejects_invalid_nonce(client, monkeypatch):
    configure_sso(monkeypatch)
    set_flow_cookie(client)

    claims = valid_claims(client)
    claims["nonce"] = "attacker-controlled-nonce"
    mock_token_exchange(monkeypatch, claims)

    response = client.post(
        "/api/v1/sso/callback",
        json={"code": "a" * 32, "state": "test-state-1234567890"},
    )

    assert response.status_code == 502


@pytest.mark.parametrize(
    ("claim", "value"),
    [("aud", "another-client"), ("exp", 1)],
)
def test_callback_rejects_invalid_token_claims(client, monkeypatch, claim, value):
    configure_sso(monkeypatch)
    set_flow_cookie(client)

    claims = valid_claims(client)
    claims[claim] = value
    mock_token_exchange(monkeypatch, claims)

    response = client.post(
        "/api/v1/sso/callback",
        json={"code": "a" * 32, "state": "test-state-1234567890"},
    )

    assert response.status_code == 502


def test_callback_rejects_invalid_signature(client, monkeypatch):
    configure_sso(monkeypatch)
    set_flow_cookie(client)
    mock_token_exchange(monkeypatch, valid_claims(client), publish_wrong_key=True)

    response = client.post(
        "/api/v1/sso/callback",
        json={"code": "a" * 32, "state": "test-state-1234567890"},
    )

    assert response.status_code == 502


def test_callback_success_creates_session(client, monkeypatch):
    configure_sso(monkeypatch)
    set_flow_cookie(client)
    claims = valid_claims(client)
    mock_token_exchange(monkeypatch, claims)

    created = {}

    def fake_create_session(db, user, expires_at, organization=None, **kwargs):
        created["user"] = user
        created["organization"] = organization
        created.update(kwargs)
        return object(), "fake-session-token"

    monkeypatch.setattr(sso, "create_session", fake_create_session)

    response = client.post(
        "/api/v1/sso/callback",
        json={
            "code": "a" * 32,
            "state": "test-state-1234567890",
        },
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(client.sso_test_data["user_id"])
    assert created["user"] is client.sso_test_data["user"]
    assert created["organization"] is client.sso_test_data["organization"]
    assert created["sibvo_subject"] == client.sso_test_data["subject_id"]
    assert str(created["sibvo_session_id"]) == claims["sid"]
    assert "set-cookie" in response.headers
    assert "fake-session-token" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    ("path", "payload", "expected_detail"),
    [
        (
            "/api/v1/auth/login",
            {"email": "user@example.com", "password": "password"},
            "Sign in through SIBVO.",
        ),
        (
            "/api/v1/auth/signup",
            {
                "email": "new@example.com",
                "password": "a-secure-password-123",
                "display_name": "New User",
                "organization_name": "New Workspace",
            },
            "Create your account through SIBVO.",
        ),
    ],
)
def test_production_does_not_expose_local_login_or_signup(
    client,
    monkeypatch,
    path,
    payload,
    expected_detail,
):
    settings = auth_api.get_settings().model_copy(
        update={"app_environment": "production"}
    )
    monkeypatch.setattr(auth_api, "get_settings", lambda: settings)

    response = client.post(path, json=payload)

    assert response.status_code == 410
    assert expected_detail in response.text


def test_callback_rejects_missing_identity_mapping(client, monkeypatch):
    configure_sso(monkeypatch)
    set_flow_cookie(client)
    mock_token_exchange(monkeypatch, valid_claims(client))

    client.sso_test_data["db"].scalar = lambda statement: None

    response = client.post(
        "/api/v1/sso/callback",
        json={
            "code": "a" * 32,
            "state": "test-state-1234567890",
        },
    )

    assert response.status_code == 403
