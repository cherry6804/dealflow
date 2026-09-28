"""Tests for the DealFlow audit event service."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.audit.service import create_authorization_audit_event
from app.config import get_settings
from app.db.models.audit_event import AuditDecision, AuditEventType
from app.db.models.organization import Organization
from app.db.models.user import User


settings = get_settings()

TEST_DATABASE_URL = settings.database_url

TestingEngine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
)

TestingSessionLocal = sessionmaker(
    bind=TestingEngine,
    autoflush=False,
    autocommit=False,
)


def create_test_user(db: Session) -> User:
    """Create a persisted test user."""
    user = User(
        email=f"user-{uuid4()}@example.com",
        display_name="Audit Test User",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_test_organization(db: Session) -> Organization:
    """Create a persisted test organization."""
    organization = Organization(
        name=f"Audit Test Organization {uuid4()}",
        is_active=True,
    )
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def audit_session() -> Session:
    """Provide a database session for audit service tests."""
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_create_allowed_authorization_audit_event(
    audit_session: Session,
) -> None:
    """Create an allowed authorization audit event."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    event = create_authorization_audit_event(
        audit_session,
        user_id=user.id,
        organization_id=organization.id,
        action="lead.read",
        decision=AuditDecision.ALLOWED,
        permission_key="lead.read",
        resource_type="lead",
        resource_id="lead-123",
        correlation_id="request-123",
    )

    assert event.id is not None
    assert event.user_id == user.id
    assert event.organization_id == organization.id
    assert event.event_type == AuditEventType.AUTHORIZATION.value
    assert event.action == "lead.read"
    assert event.decision == AuditDecision.ALLOWED.value
    assert event.permission_key == "lead.read"
    assert event.resource_type == "lead"
    assert event.resource_id == "lead-123"
    assert event.correlation_id == "request-123"
    assert event.event_metadata is None
    assert event.occurred_at is not None


def test_create_denied_authorization_audit_event(
    audit_session: Session,
) -> None:
    """Create a denied authorization audit event."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    event = create_authorization_audit_event(
        audit_session,
        user_id=user.id,
        organization_id=organization.id,
        action="lead.delete",
        decision=AuditDecision.DENIED,
        permission_key="lead.delete",
    )

    assert event.id is not None
    assert event.user_id == user.id
    assert event.organization_id == organization.id
    assert event.event_type == AuditEventType.AUTHORIZATION.value
    assert event.action == "lead.delete"
    assert event.decision == AuditDecision.DENIED.value
    assert event.permission_key == "lead.delete"


def test_action_is_normalized(
    audit_session: Session,
) -> None:
    """Normalize surrounding whitespace from an audit action."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    event = create_authorization_audit_event(
        audit_session,
        user_id=user.id,
        organization_id=organization.id,
        action="  lead.read  ",
        decision=AuditDecision.ALLOWED,
    )

    assert event.action == "lead.read"


def test_permission_key_is_normalized(
    audit_session: Session,
) -> None:
    """Normalize surrounding whitespace from a permission key."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    event = create_authorization_audit_event(
        audit_session,
        user_id=user.id,
        organization_id=organization.id,
        action="lead.read",
        decision=AuditDecision.ALLOWED,
        permission_key="  lead.read  ",
    )

    assert event.permission_key == "lead.read"


def test_optional_context_can_be_omitted(
    audit_session: Session,
) -> None:
    """Allow authorization events without optional resource context."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    event = create_authorization_audit_event(
        audit_session,
        user_id=user.id,
        organization_id=organization.id,
        action="dashboard.read",
        decision=AuditDecision.ALLOWED,
    )

    assert event.permission_key is None
    assert event.resource_type is None
    assert event.resource_id is None
    assert event.correlation_id is None


def test_empty_action_is_rejected(
    audit_session: Session,
) -> None:
    """Reject an empty authorization action."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    with pytest.raises(ValueError, match="Audit action cannot be empty"):
        create_authorization_audit_event(
            audit_session,
            user_id=user.id,
            organization_id=organization.id,
            action="   ",
            decision=AuditDecision.ALLOWED,
        )


def test_action_longer_than_allowed_limit_is_rejected(
    audit_session: Session,
) -> None:
    """Reject an authorization action exceeding the database limit."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    with pytest.raises(
        ValueError,
        match="Audit action cannot exceed 200 characters",
    ):
        create_authorization_audit_event(
            audit_session,
            user_id=user.id,
            organization_id=organization.id,
            action="a" * 201,
            decision=AuditDecision.ALLOWED,
        )


def test_empty_permission_key_is_rejected(
    audit_session: Session,
) -> None:
    """Reject an empty permission key when supplied."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    with pytest.raises(
        ValueError,
        match="Permission key cannot be empty",
    ):
        create_authorization_audit_event(
            audit_session,
            user_id=user.id,
            organization_id=organization.id,
            action="lead.read",
            decision=AuditDecision.ALLOWED,
            permission_key="   ",
        )


def test_empty_optional_context_is_rejected(
    audit_session: Session,
) -> None:
    """Reject empty optional context values."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    with pytest.raises(
        ValueError,
        match="Resource type cannot be empty",
    ):
        create_authorization_audit_event(
            audit_session,
            user_id=user.id,
            organization_id=organization.id,
            action="lead.read",
            decision=AuditDecision.ALLOWED,
            resource_type="   ",
        )


def test_audit_service_does_not_commit_transaction(
    audit_session: Session,
) -> None:
    """Ensure transaction ownership remains with the caller."""
    user = create_test_user(audit_session)
    organization = create_test_organization(audit_session)

    event = create_authorization_audit_event(
        audit_session,
        user_id=user.id,
        organization_id=organization.id,
        action="lead.read",
        decision=AuditDecision.ALLOWED,
    )

    event_id = event.id

    audit_session.rollback()

    persisted_event = audit_session.get(type(event), event_id)

    assert persisted_event is None