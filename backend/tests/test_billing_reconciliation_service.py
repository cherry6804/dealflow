
"""Focused unit tests for billing reconciliation."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.billing.reconciliation_service import reconcile_webhook_event


def test_existing_reconciliation_is_idempotent():
    db = MagicMock()
    event_id = uuid4()
    existing = SimpleNamespace(
        id=uuid4(),
        webhook_event_id=event_id,
        status="MATCHED",
    )
    db.scalar.return_value = existing

    result = reconcile_webhook_event(db, webhook_event_id=event_id)

    assert result.record is existing
    assert result.created is False
    db.get.assert_not_called()
    db.execute.assert_not_called()


def test_missing_webhook_event_is_rejected():
    db = MagicMock()
    db.scalar.return_value = None
    db.get.return_value = None
    event_id = uuid4()

    with pytest.raises(ValueError, match="not found"):
        reconcile_webhook_event(db, webhook_event_id=event_id)

    db.execute.assert_not_called()
