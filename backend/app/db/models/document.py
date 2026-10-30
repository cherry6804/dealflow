
"""Tenant-scoped document metadata model.

Document binary content is stored through a storage abstraction implemented
in a later story. This model stores metadata and the storage reference only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Document(Base):
    """Metadata and tenant-scoped associations for an uploaded document."""

    __tablename__ = "documents"

    # Supported document categories.
    CATEGORY_IDENTITY_KYC = "IDENTITY_KYC"
    CATEGORY_OWNERSHIP_TITLE = "OWNERSHIP_TITLE"
    CATEGORY_LEGAL_COMPLIANCE = "LEGAL_COMPLIANCE"
    CATEGORY_PROPERTY_RECORD = "PROPERTY_RECORD"
    CATEGORY_MARKETING = "MARKETING"
    CATEGORY_AGREEMENT = "AGREEMENT"
    CATEGORY_FINANCIAL = "FINANCIAL"
    CATEGORY_CUSTOMER = "CUSTOMER"
    CATEGORY_DEAL = "DEAL"
    CATEGORY_OTHER = "OTHER"

    CATEGORIES = (
        CATEGORY_IDENTITY_KYC,
        CATEGORY_OWNERSHIP_TITLE,
        CATEGORY_LEGAL_COMPLIANCE,
        CATEGORY_PROPERTY_RECORD,
        CATEGORY_MARKETING,
        CATEGORY_AGREEMENT,
        CATEGORY_FINANCIAL,
        CATEGORY_CUSTOMER,
        CATEGORY_DEAL,
        CATEGORY_OTHER,
    )

    # Classification is metadata, not a substitute for authorization.
    CLASSIFICATION_PUBLIC = "PUBLIC"
    CLASSIFICATION_INTERNAL = "INTERNAL"
    CLASSIFICATION_CONFIDENTIAL = "CONFIDENTIAL"
    CLASSIFICATION_RESTRICTED = "RESTRICTED"

    ACCESS_CLASSIFICATIONS = (
        CLASSIFICATION_PUBLIC,
        CLASSIFICATION_INTERNAL,
        CLASSIFICATION_CONFIDENTIAL,
        CLASSIFICATION_RESTRICTED,
    )

    STATUS_PENDING = "PENDING"
    STATUS_AVAILABLE = "AVAILABLE"
    STATUS_ARCHIVED = "ARCHIVED"
    STATUS_DELETED = "DELETED"

    STATUSES = (
        STATUS_PENDING,
        STATUS_AVAILABLE,
        STATUS_ARCHIVED,
        STATUS_DELETED,
    )

    # Primary identity and tenant ownership.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # User-facing metadata.
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    category: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=CATEGORY_OTHER,
        server_default=text("'OTHER'"),
    )

    document_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # File metadata. The actual file bytes are not stored in this table.
    content_type: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    file_extension: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    file_size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    checksum_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # Populated by the storage/upload implementation in later stories.
    storage_backend: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    storage_key: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    # Access classification and lifecycle state.
    access_classification: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=CLASSIFICATION_INTERNAL,
        server_default=text("'INTERNAL'"),
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=STATUS_PENDING,
        server_default=text("'PENDING'"),
    )

    # Flexible labels and non-sensitive application metadata.
    tags: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Optional links to business records. Composite foreign keys below
    # ensure a linked record belongs to the same organization.
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    # Version metadata. Version lifecycle behavior is implemented separately.
    version_number: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    is_current_version: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    # User references. Application services must still validate membership
    # and authorization within the active organization.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Lifecycle timestamps.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        # Supports composite tenant-scoped references to this table.
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_documents_id_organization_id",
        ),
        UniqueConstraint(
            "organization_id",
            "storage_key",
            name="uq_documents_org_storage_key",
        ),

        # A document cannot reference a business record belonging to
        # another organization.
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_documents_lead_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["property_id", "organization_id"],
            ["properties.id", "properties.organization_id"],
            name="fk_documents_property_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_documents_deal_tenant",
            ondelete="RESTRICT",
        ),

        # Validate controlled metadata values at the database boundary.
        CheckConstraint(
            "category IN "
            "('IDENTITY_KYC', 'OWNERSHIP_TITLE', 'LEGAL_COMPLIANCE', "
            "'PROPERTY_RECORD', 'MARKETING', 'AGREEMENT', 'FINANCIAL', "
            "'CUSTOMER', 'DEAL', 'OTHER')",
            name="ck_documents_category",
        ),
        CheckConstraint(
            "access_classification IN "
            "('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name="ck_documents_access_classification",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'AVAILABLE', 'ARCHIVED', 'DELETED')",
            name="ck_documents_status",
        ),
        CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes >= 0",
            name="ck_documents_file_size_nonnegative",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_documents_version_positive",
        ),

        # Tenant-scoped indexes for common filtering and listing.
        Index(
            "ix_documents_org_category",
            "organization_id",
            "category",
        ),
        Index(
            "ix_documents_org_classification",
            "organization_id",
            "access_classification",
        ),
        Index(
            "ix_documents_org_created_at",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_documents_org_deal",
            "organization_id",
            "deal_id",
        ),
        Index(
            "ix_documents_org_lead",
            "organization_id",
            "lead_id",
        ),
        Index(
            "ix_documents_org_property",
            "organization_id",
            "property_id",
        ),
        Index(
            "ix_documents_org_status",
            "organization_id",
            "status",
        ),
    )
