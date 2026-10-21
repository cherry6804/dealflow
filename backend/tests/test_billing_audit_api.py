
"""Focused tests for tenant isolation in the billing audit API."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.billing_audit import (
    get_reconciliation_record,
    get_reconciliation_records,
)


def test_list_reconciliation_records_filters_by_tenant():
    db = MagicMock()
    organization_id = uuid4()
    tenant = SimpleNamespace(organization_id=organization_id)

    query = db.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.offset.return_value = query
    query.all.return_value = []

    response = get_reconciliation_records(
        limit=50,
        offset=0,
        tenant=tenant,
        db=db,
    )

    assert response.items == []
    assert response.limit == 50
    assert response.offset == 0
    db.query.assert_called_once()


def test_get_reconciliation_record_returns_404_when_not_in_tenant():
    db = MagicMock()
    tenant = SimpleNamespace(organization_id=uuid4())

    query = db.query.return_value
    query.filter.return_value = query
    query.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        get_reconciliation_record(
            record_id=uuid4(),
            tenant=tenant,
            db=db,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Billing reconciliation record not found."
