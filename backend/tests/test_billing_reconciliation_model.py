
"""Tests for billing reconciliation records."""

from uuid import uuid4

from app.db.models.billing_reconciliation_record import (
    BillingReconciliationRecord,
)


def test_reconciliation_record_fields() -> None:
    record = BillingReconciliationRecord(
        webhook_event_id=uuid4(),
        organization_id=uuid4(),
        status=BillingReconciliationRecord.STATUS_MATCHED,
        summary="Subscription reference matched.",
        details={"payment_confirmed": False},
    )

    assert record.webhook_event_id is not None
    assert record.organization_id is not None
    assert record.status == "MATCHED"
    assert record.details["payment_confirmed"] is False


def test_reconciliation_status_values() -> None:
    assert BillingReconciliationRecord.STATUS_VALUES == (
        "MATCHED",
        "MISMATCHED",
        "FAILED",
    )


def test_reconciliation_model_has_expected_indexes() -> None:
    indexes = {
        index.name
        for index in BillingReconciliationRecord.__table__.indexes
    }

    assert "ix_billing_reconciliation_records_event_created" in indexes
    assert "ix_billing_reconciliation_records_organization_id" in indexes
