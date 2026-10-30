
"""Create plans and entitlements.

Revision ID: a530aec6d3d1
Revises: 1fa307647bd4
"""

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "a530aec6d3d1"
down_revision: Union[str, Sequence[str], None] = "1fa307647bd4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create plan catalog, seed plans, and link subscriptions."""

    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("monthly_price_paise", sa.Integer(), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default="INR",
            nullable=False,
        ),
        sa.Column("included_seats", sa.Integer(), nullable=True),
        sa.Column(
            "is_custom_pricing",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(code) > 0",
            name="ck_plans_code_not_empty",
        ),
        sa.CheckConstraint(
            "monthly_price_paise IS NULL OR monthly_price_paise >= 0",
            name="ck_plans_price_nonnegative",
        ),
        sa.CheckConstraint(
            "included_seats IS NULL OR included_seats > 0",
            name="ck_plans_included_seats_positive",
        ),
        sa.CheckConstraint(
            "currency = 'INR'",
            name="ck_plans_currency_inr",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "plan_entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value_type", sa.String(length=10), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(key) > 0",
            name="ck_plan_entitlements_key_not_empty",
        ),
        sa.CheckConstraint(
            "value_type IN ('BOOLEAN', 'INTEGER', 'STRING', 'JSON')",
            name="ck_plan_entitlements_value_type",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "key",
            name="uq_plan_entitlements_plan_key",
        ),
    )

    op.create_index(
        "ix_plan_entitlements_plan_id",
        "plan_entitlements",
        ["plan_id"],
    )

    # UUIDs are fixed in this migration so seeded plan identities are stable.
    plan_data = [
        {
            "id": uuid.UUID("a530aec6-0000-4000-8000-000000000001"),
            "code": "solo",
            "name": "Solo",
            "description": "For an individual real estate professional.",
            "monthly_price_paise": 49900,
            "currency": "INR",
            "included_seats": 1,
            "is_custom_pricing": False,
            "is_active": True,
        },
        {
            "id": uuid.UUID("a530aec6-0000-4000-8000-000000000002"),
            "code": "starter",
            "name": "Starter",
            "description": "For small teams getting started with DealFlow.",
            "monthly_price_paise": 99900,
            "currency": "INR",
            "included_seats": 2,
            "is_custom_pricing": False,
            "is_active": True,
        },
        {
            "id": uuid.UUID("a530aec6-0000-4000-8000-000000000003"),
            "code": "growth",
            "name": "Growth",
            "description": "For growing teams needing workflow and reporting capabilities.",
            "monthly_price_paise": 249900,
            "currency": "INR",
            "included_seats": 5,
            "is_custom_pricing": False,
            "is_active": True,
        },
        {
            "id": uuid.UUID("a530aec6-0000-4000-8000-000000000004"),
            "code": "business",
            "name": "Business",
            "description": "For larger teams needing more granular administration.",
            "monthly_price_paise": 499900,
            "currency": "INR",
            "included_seats": 10,
            "is_custom_pricing": False,
            "is_active": True,
        },
        {
            "id": uuid.UUID("a530aec6-0000-4000-8000-000000000005"),
            "code": "enterprise",
            "name": "Enterprise",
            "description": "Custom pricing, seats, and negotiated entitlements.",
            "monthly_price_paise": None,
            "currency": "INR",
            "included_seats": None,
            "is_custom_pricing": True,
            "is_active": True,
        },
    ]

    plans_table = sa.table(
        "plans",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("monthly_price_paise", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("included_seats", sa.Integer()),
        sa.column("is_custom_pricing", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(plans_table, plan_data)

    # Add the nullable link first, preserving all existing subscriptions.
    op.add_column(
        "subscriptions",
        sa.Column("plan_id", sa.Uuid(), nullable=True),
    )

    # Match legacy plan codes case-insensitively after trimming whitespace.
    # Unmatched codes are intentionally retained with plan_id = NULL.
    op.execute(
        sa.text(
            """
            UPDATE subscriptions AS s
            SET plan_id = p.id
            FROM plans AS p
            WHERE lower(trim(s.plan_code)) = p.code
              AND s.plan_id IS NULL
            """
        )
    )

    op.create_foreign_key(
        "fk_subscriptions_plan_id_plans",
        "subscriptions",
        "plans",
        ["plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_subscriptions_plan_id",
        "subscriptions",
        ["plan_id"],
    )

    # Plan capabilities are catalog data. DF-139 will enforce entitlements.
    common_features = {
        "leads_contacts_customers",
        "property_listings_requirements",
        "followups_tasks_site_visits",
        "basic_pipeline_dashboard",
        "standard_access_controls",
        "basic_import_export",
    }

    starter_features = {
        "shared_workspace",
        "lead_assignment",
        "requirement_property_matching",
        "interaction_history_documents",
        "team_reporting",
        "workflow_configuration",
    }

    growth_features = {
        "configurable_lead_stages",
        "custom_fields",
        "manager_reporting",
        "flexible_record_sharing",
        "workflow_automation",
        "enhanced_activity_history",
        "permission_presets",
    }

    business_features = {
        "custom_roles",
        "granular_permissions",
        "branch_access_controls",
        "advanced_workflows",
        "advanced_reporting_exports",
        "org_audit_admin",
    }

    feature_sets = {
        "solo": common_features,
        "starter": common_features | starter_features,
        "growth": common_features | starter_features | growth_features,
        "business": (
            common_features
            | starter_features
            | growth_features
            | business_features
        ),
    }

    entitlement_rows = []

    for plan in plan_data:
        # Enterprise limits and feature access must be agreed per customer.
        if plan["code"] == "enterprise":
            continue

        entitlement_rows.append(
            {
                "id": uuid.uuid5(
                    plan["id"],
                    "entitlement:max_seats",
                ),
                "plan_id": plan["id"],
                "key": "max_seats",
                "value_type": "INTEGER",
                "value": plan["included_seats"],
                "description": "Maximum number of included seats.",
            }
        )

        for feature in sorted(feature_sets[plan["code"]]):
            entitlement_rows.append(
                {
                    "id": uuid.uuid5(
                        plan["id"],
                        f"entitlement:{feature}",
                    ),
                    "plan_id": plan["id"],
                    "key": feature,
                    "value_type": "BOOLEAN",
                    "value": True,
                    "description": (
                        f"Access to {feature.replace('_', ' ')}."
                    ),
                }
            )

    entitlements_table = sa.table(
        "plan_entitlements",
        sa.column("id", sa.Uuid()),
        sa.column("plan_id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("value_type", sa.String()),
        sa.column("value", sa.JSON()),
        sa.column("description", sa.String()),
    )
    op.bulk_insert(entitlements_table, entitlement_rows)


def downgrade() -> None:
    """Remove the plan catalog and its subscription link."""

    op.drop_index(
        "ix_subscriptions_plan_id",
        table_name="subscriptions",
    )
    op.drop_constraint(
        "fk_subscriptions_plan_id_plans",
        "subscriptions",
        type_="foreignkey",
    )
    op.drop_column("subscriptions", "plan_id")

    op.drop_index(
        "ix_plan_entitlements_plan_id",
        table_name="plan_entitlements",
    )
    op.drop_table("plan_entitlements")
    op.drop_table("plans")
