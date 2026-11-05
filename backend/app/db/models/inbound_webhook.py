"""Inbound webhook endpoints and their delivery records (DFR1-012).

An endpoint is the server-side configuration that trusts one inbound URL: its organization, provider key, verifier, status and secret.
The URL carries only the endpoint identifier. The organization is read from this row, never from the request or the payload.

The signing secret is stored as AES-256-GCM ciphertext from the existing provider-secrets cipher. Its associated data binds it to the
endpoint, organization and version, so a copied ciphertext does not decrypt on another row.

A delivery row records every verified or refused delivery. An accepted delivery stores the redacted payload and is unique per endpoint
and provider event ID, which is what makes duplicate deliveries safe. Refused deliveries store no body, only its hash and size.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InboundWebhookEndpoint(Base):
    __tablename__ = "inbound_webhook_endpoints"

    STATUS_ACTIVE = "active"
    STATUS_DISABLED = "disabled"

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_inbound_webhook_endpoints_status",
        ),
        CheckConstraint(
            "secret_version >= 1", name="ck_inbound_webhook_endpoints_version_positive"
        ),
        CheckConstraint(
            "(status = 'active' AND secret_ciphertext IS NOT NULL AND secret_key_id IS NOT NULL"
            " AND secret_algorithm IS NOT NULL) OR (status = 'disabled' AND secret_ciphertext IS NULL)",
            name="ck_inbound_webhook_endpoints_secret_state",
        ),
        UniqueConstraint(
            "id", "organization_id", name="uq_inbound_webhook_endpoints_id_organization"
        ),
        Index("ix_inbound_webhook_endpoints_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    verifier_key: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_ACTIVE
    )
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=True
    )
    secret_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    secret_algorithm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    disabled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InboundWebhookDelivery(Base):
    __tablename__ = "inbound_webhook_deliveries"

    OUTCOME_ACCEPTED = "accepted"
    OUTCOME_DUPLICATE = "duplicate"
    OUTCOME_CONFLICT = "conflict"
    OUTCOME_REJECTED = "rejected"
    OUTCOME_FAILED = "failed"
    OUTCOMES = (
        OUTCOME_ACCEPTED,
        OUTCOME_DUPLICATE,
        OUTCOME_CONFLICT,
        OUTCOME_REJECTED,
        OUTCOME_FAILED,
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'conflict', 'rejected', 'failed')",
            name="ck_inbound_webhook_deliveries_outcome",
        ),
        CheckConstraint(
            "body_bytes >= 0", name="ck_inbound_webhook_deliveries_body_bytes"
        ),
        ForeignKeyConstraint(
            ["endpoint_id", "organization_id"],
            [
                "inbound_webhook_endpoints.id",
                "inbound_webhook_endpoints.organization_id",
            ],
            name="fk_inbound_webhook_deliveries_endpoint_tenant",
            ondelete="RESTRICT",
        ),
        # One accepted delivery per endpoint and provider event. This is what makes a duplicate delivery safe under concurrency.
        Index(
            "uq_inbound_webhook_deliveries_accepted_event",
            "endpoint_id",
            "provider_event_id",
            unique=True,
            postgresql_where=text("outcome = 'accepted'"),
        ),
        Index(
            "ix_inbound_webhook_deliveries_org_received",
            "organization_id",
            "received_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signature_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    timestamp_header: Mapped[str | None] = mapped_column(String(20), nullable=True)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    body_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    envelope: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    outbox_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
