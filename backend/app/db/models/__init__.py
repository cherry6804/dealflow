"""DealFlow database models."""

from app.db.models.activity import Activity
from app.db.models.knowledge_chunk import KnowledgeChunk
from app.db.models.ai_task_route import AiTaskRoute
from app.db.models.audit_event import AuditEvent
from app.db.models.auth_login_rate_limit import AuthLoginRateLimit
from app.db.models.auth_session import AuthSession
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.billing_reconciliation_record import (
    BillingReconciliationRecord,
)
from app.db.models.billing_webhook_event import BillingWebhookEvent
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_history import CustomerRequirementHistory
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_possession_parking_preference import (
    CustomerRequirementPossessionParkingPreference,
)
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.deal import Deal
from app.db.models.deal_commission import DealCommission
from app.db.models.deal_negotiation import (
    DealNegotiation,
    DealNegotiationHistory,
)
from app.db.models.deal_stage_history import DealStageHistory
from app.db.models.document import Document
from app.db.models.agent import Agent, AgentExecution, AgentExecutionStep, AgentVersion
from app.db.models.document_review import DocumentReview
from app.db.models.lead_intake import LeadIntakeSubmission, LeadQualificationResult
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.db.models.email_outbox_message import EmailOutboxMessage
from app.db.models.email_verification_token import EmailVerificationToken
from app.db.models.follow_up import FollowUp
from app.db.models.import_batch import ImportBatch
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationPreference
from app.db.models.organization import Organization
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.payment_milestone import PaymentMilestone
from app.db.models.permission import Permission
from app.db.models.plan import Plan
from app.db.models.plan_entitlement import PlanEntitlement
from app.db.models.property import Property
from app.db.models.referral import Referral
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.db.models.requirement_property_shortlist import (
    RequirementPropertyShortlist,
)
from app.db.models.requirement_shortlist_event import RequirementShortlistEvent
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.sibvo_identity_link import SibvoIdentityLink
from app.db.models.sibvo_organization_link import SibvoOrganizationLink
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.organization_usage_alert_settings import OrganizationUsageAlertSettings
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest, RetentionPolicy
from app.db.models.contact_consent import ContactConsentRecord
from app.db.models.provider_connection import ProviderConnection
from app.db.models.approval_request import ApprovalRequest
from app.db.models.channel_policy import ChannelPolicy, ContactDoNotDisturb
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.execution_rate_limit_window import ExecutionRateLimitWindow
from app.db.models.provider_credential import ProviderCredential
from app.db.models.team_member_removal import TeamMemberRemoval
from app.db.models.site_visit import SiteVisit
from app.db.models.subscription import Subscription
from app.db.models.team_invitation import TeamInvitation
from app.db.models.user import User

from app.db.models.organization_entitlement_snapshot import OrganizationEntitlementSnapshot
from app.db.models.outbox_event import OutboxEvent
from app.db.models.outbox_replay_record import OutboxReplayRecord
from app.db.models.provider_connection import ProviderConnection
from app.db.models.provider_verification_attempt import ProviderVerificationAttempt

__all__ = [
    "OrganizationEntitlementSnapshot",
    "OutboxEvent",
    "OutboxReplayRecord",
    "ProviderConnection",
    "ProviderVerificationAttempt",
    "Activity",
    "AuditEvent",
    "KnowledgeChunk",
    "AiTaskRoute",
    "AuthLoginRateLimit",
    "AuthSession",
    "AutomationExecution",
    "AutomationRule",
    "BillingReconciliationRecord",
    "BillingWebhookEvent",
    "Contact",
    "CustomerProfile",
    "CustomerRequirement",
    "CustomerRequirementHistory",
    "CustomerRequirementLocation",
    "CustomerRequirementPossessionParkingPreference",
    "CustomerRequirementPropertyPreference",
    "Deal",
    "DealCommission",
    "DealNegotiation",
    "DealNegotiationHistory",
    "DealStageHistory",
    "Document",
    "DocumentReview",
    "LeadPriorityScore",
    "LeadPriorityCorrection",
    "LeadIntakeSubmission",
    "LeadQualificationResult",
    "Agent",
    "AgentVersion",
    "AgentExecution",
    "AgentExecutionStep",
    "EmailOutboxMessage",
    "EmailVerificationToken",
    "FollowUp",
    "ImportBatch",
    "Lead",
    "Membership",
    "MembershipRole",
    "Notification",
    "NotificationPreference",
    "Organization",
    "PasswordResetToken",
    "PaymentMilestone",
    "Permission",
    "Plan",
    "PlanEntitlement",
    "Property",
    "Referral",
    "RequirementMatchRun",
    "RequirementMatchRunResult",
    "RequirementPropertyShortlist",
    "RequirementShortlistEvent",
    "Role",
    "RolePermission",
    "SibvoIdentityLink",
    "SibvoOrganizationLink",
    "AiUsageEvent",
    "LegalHold",
    "PrivacyDataRequest",
    "ContactConsentRecord",
    "ProviderConnection",
    "ApprovalRequest",
    "ChannelPolicy",
    "ContactDoNotDisturb",
    "RetentionPolicy",
    "OrganizationCapabilitySetting",
    "ExecutionRateLimitWindow",
    "ProviderCredential",
    "OrganizationUsageBudget",
    "OrganizationUsageAlertSettings",
    "TeamMemberRemoval",
    "SiteVisit",
    "Subscription",
    "TeamInvitation",
    "User",
]
