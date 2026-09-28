import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import CurrentUserContext
from app.auth.password import hash_password
from app.auth.service import create_session
from app.config import get_settings
from app.db.base import Base
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext, get_tenant_context


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def override_get_db_session() -> Generator[Session, None, None]:
    """Provide a database session for tenant dependency tests."""
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()


api_test_app = FastAPI()

api_test_app.dependency_overrides[get_db_session] = override_get_db_session


@api_test_app.get("/tenant-protected")
def tenant_protected_endpoint(
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, str]:
    """Return verified tenant information."""
    return {
        "organization_id": str(tenant.organization_id),
        "organization_name": tenant.organization.name,
        "user_id": str(tenant.membership.user_id),
    }


client = TestClient(api_test_app)


def setup_function() -> None:
    """Create a clean database before each test."""
    Base.metadata.create_all(engine)


def teardown_function() -> None:
    """Remove all test tables after each test."""
    Base.metadata.drop_all(engine)


def teardown_module() -> None:
    """Clear dependency overrides after the module finishes."""
    api_test_app.dependency_overrides.clear()


def create_user() -> User:
    """Create a test user."""
    with TestingSessionLocal() as session:
        user = User(
            id=uuid.uuid4(),
            email=f"tenant-{uuid.uuid4()}@example.com",
            display_name="Tenant User",
            password_hash=hash_password("StrongPassword!123"),
            is_active=True,
        )

        session.add(user)
        session.commit()
        session.refresh(user)

        return user


def create_organization(
    is_active: bool = True,
) -> Organization:
    """Create a test organization."""
    with TestingSessionLocal() as session:
        organization = Organization(
            id=uuid.uuid4(),
            name=f"Tenant Organization {uuid.uuid4()}",
            is_active=is_active,
        )

        session.add(organization)
        session.commit()
        session.refresh(organization)

        return organization


def create_membership(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    is_active: bool = True,
) -> Membership:
    """Create a test organization membership."""
    with TestingSessionLocal() as session:
        membership = Membership(
            user_id=user_id,
            organization_id=organization_id,
            is_active=is_active,
        )

        session.add(membership)
        session.commit()
        session.refresh(membership)

        return membership


def create_session_for_user(user: User) -> str:
    """Create an authenticated session for a test user."""
    with TestingSessionLocal() as session:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        _, token = create_session(
            db=session,
            user=user,
            expires_at=expires_at,
        )

        return token


def test_tenant_context_accepts_active_membership() -> None:
    user = create_user()
    organization = create_organization()
    create_membership(
        user_id=user.id,
        organization_id=organization.id,
    )

    token = create_session_for_user(user)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": str(organization.id),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "organization_id": str(organization.id),
        "organization_name": organization.name,
        "user_id": str(user.id),
    }


def test_tenant_context_rejects_missing_organization_header() -> None:
    user = create_user()
    token = create_session_for_user(user)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Organization context is required.",
    }


def test_tenant_context_rejects_invalid_organization_id() -> None:
    user = create_user()
    token = create_session_for_user(user)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": "not-a-uuid",
        },
    )

    assert response.status_code == 422


def test_tenant_context_rejects_non_member() -> None:
    user = create_user()
    organization = create_organization()

    token = create_session_for_user(user)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": str(organization.id),
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Organization access denied.",
    }


def test_tenant_context_rejects_inactive_membership() -> None:
    user = create_user()
    organization = create_organization()

    create_membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=False,
    )

    token = create_session_for_user(user)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": str(organization.id),
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Organization access denied.",
    }


def test_tenant_context_rejects_inactive_organization() -> None:
    user = create_user()
    organization = create_organization(is_active=False)

    create_membership(
        user_id=user.id,
        organization_id=organization.id,
    )

    token = create_session_for_user(user)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": str(organization.id),
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Organization access denied.",
    }


def test_tenant_context_supports_multiple_organizations() -> None:
    user = create_user()
    organization_a = create_organization()
    organization_b = create_organization()

    create_membership(
        user_id=user.id,
        organization_id=organization_a.id,
    )
    create_membership(
        user_id=user.id,
        organization_id=organization_b.id,
    )

    token = create_session_for_user(user)

    response_a = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": str(organization_a.id),
        },
    )

    response_b = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": str(organization_b.id),
        },
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    assert response_a.json()["organization_id"] == str(organization_a.id)
    assert response_b.json()["organization_id"] == str(organization_b.id)


def test_tenant_context_prevents_cross_tenant_access() -> None:
    user_a = create_user()
    user_b = create_user()

    organization_a = create_organization()
    organization_b = create_organization()

    create_membership(
        user_id=user_a.id,
        organization_id=organization_a.id,
    )
    create_membership(
        user_id=user_b.id,
        organization_id=organization_b.id,
    )

    token_a = create_session_for_user(user_a)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token_a,
        },
        headers={
            "X-Organization-ID": str(organization_b.id),
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Organization access denied.",
    }


def test_tenant_context_requires_authentication() -> None:
    organization = create_organization()

    response = client.get(
        "/tenant-protected",
        headers={
            "X-Organization-ID": str(organization.id),
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required.",
    }


def test_tenant_context_rejects_inactive_user() -> None:
    user = create_user()

    with TestingSessionLocal() as session:
        user.is_active = False
        session.merge(user)
        session.commit()

    organization = create_organization()

    create_membership(
        user_id=user.id,
        organization_id=organization.id,
    )

    token = create_session_for_user(user)

    response = client.get(
        "/tenant-protected",
        cookies={
            get_settings().auth_cookie_name: token,
        },
        headers={
            "X-Organization-ID": str(organization.id),
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication required.",
    }