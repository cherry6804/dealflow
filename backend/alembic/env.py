
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.base import Base
from app.db.models.audit_event import AuditEvent
from app.db.models.auth_session import AuthSession
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import (
    CustomerRequirementLocation,
)
from app.db.models.referral import Referral
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.requirement_property_shortlist import (
    RequirementPropertyShortlist,
)
from app.db.models.customer_requirement_possession_parking_preference import (
    CustomerRequirementPossessionParkingPreference,
)
from app.db.models.automation_rule import AutomationRule
from app.db.models.import_batch import ImportBatch
from app.db.models.activity import Activity
from app.db.models.follow_up import FollowUp
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.db.models.requirement_shortlist_event import RequirementShortlistEvent
from app.db.models.deal import Deal
from app.db.models.deal_negotiation import (
    DealNegotiation,
    DealNegotiationHistory,
)
from app.db.models.billing_reconciliation_record import (
    BillingReconciliationRecord,
)
from app.db.models.notification import Notification
from app.db.models.document import Document
from app.db.models.payment_milestone import PaymentMilestone
from app.db.models.deal_commission import DealCommission
from app.db.models.notification_preference import NotificationPreference
from app.db.models.subscription import Subscription
from app.db.models.plan import Plan
from app.db.models.plan_entitlement import PlanEntitlement
from app.db.models.billing_webhook_event import BillingWebhookEvent
from app.db.models.email_verification_token import EmailVerificationToken
from app.db.models.email_outbox_message import EmailOutboxMessage
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.team_invitation import TeamInvitation

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
target_metadata = Base.metadata

# An explicit Alembic sqlalchemy.url takes precedence. Otherwise, use
# the database URL loaded by the application from its environment/.env.
configured_url = config.get_main_option("sqlalchemy.url")
database_url = (
    configured_url.strip()
    if configured_url and configured_url.strip()
    else settings.database_url
)

# Safety guard: migrations are permitted only for the application database
# and the dedicated test database. This helps prevent accidental migrations
# against unrelated databases.
database_name = make_url(database_url).database

if database_name not in {"dealflow", "dealflow_test"}:
    raise RuntimeError(
        "Refusing to run Alembic against unexpected database "
        f"{database_name!r}. Allowed databases: 'dealflow', 'dealflow_test'."
    )


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a live database connection."""
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
