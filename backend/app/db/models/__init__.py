"""DealFlow database models."""

from app.db.models.audit_event import AuditEvent
from app.db.models.auth_session import AuthSession
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
from app.db.models.import_batch import ImportBatch
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.property import Property
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.models.activity import Activity
from app.db.models.follow_up import FollowUp
from app.db.models.requirement_property_shortlist import (
    RequirementPropertyShortlist,
)
from app.db.models.deal_negotiation import (
    DealNegotiation,
    DealNegotiationHistory,
)
from app.db.models.deal import Deal
from app.db.models.site_visit import SiteVisit
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.db.models.requirement_shortlist_event import RequirementShortlistEvent

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Activity",
    "Contact",
    "CustomerProfile",
    "CustomerRequirement",
    "CustomerRequirementHistory",
    "CustomerRequirementLocation",
    "CustomerRequirementPossessionParkingPreference",
    "CustomerRequirementPropertyPreference",
    "ImportBatch",
    "Lead",
    "Membership",
    "MembershipRole",
    "Organization",
    "Permission",
    "Property",
    "Role",
    "RolePermission",
    "User",
    "FollowUp",
    "RequirementPropertyShortlist",
    "RequirementMatchRun",
    "RequirementMatchRunResult",
    "RequirementShortlistEvent",
    "SiteVisit",
    "Deal",
    "DealNegotiation",
    "DealNegotiationHistory",
]
