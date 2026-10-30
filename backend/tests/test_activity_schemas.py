"""Tests for Activity request and response schemas."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.activities.schemas import (
    ActivityCreateRequest,
    ActivityListResponse,
    ActivityResponse,
)


def test_create_request_accepts_valid_activity():
    payload = ActivityCreateRequest(
        activity_type="NOTE",
        title="  Customer discussion  ",
        description="  Discussed property requirements  ",
        details={"source": "phone"},
    )

    assert payload.title == "Customer discussion"
    assert payload.description == "Discussed property requirements"
    assert payload.details == {"source": "phone"}


def test_create_request_rejects_blank_title():
    with pytest.raises(ValidationError):
        ActivityCreateRequest(
            activity_type="NOTE",
            title="   ",
        )


def test_create_request_rejects_empty_title():
    with pytest.raises(ValidationError):
        ActivityCreateRequest(
            activity_type="NOTE",
            title="",
        )


def test_create_request_rejects_invalid_activity_type():
    with pytest.raises(ValidationError):
        ActivityCreateRequest(
            activity_type="INVALID",
            title="Customer discussion",
        )


def test_create_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ActivityCreateRequest(
            activity_type="NOTE",
            title="Customer discussion",
            organization_id=str(uuid4()),
        )


def test_create_request_normalizes_blank_description():
    payload = ActivityCreateRequest(
        activity_type="NOTE",
        title="Customer discussion",
        description="   ",
    )

    assert payload.description is None


def test_create_request_accepts_optional_occurrence_time():
    occurred_at = datetime(2026, 10, 12, 10, 30, tzinfo=timezone.utc)

    payload = ActivityCreateRequest(
        activity_type="CALL",
        title="Follow-up call",
        occurred_at=occurred_at,
    )

    assert payload.occurred_at == occurred_at


def test_response_schema_accepts_activity_fields():
    now = datetime.now(timezone.utc)

    response = ActivityResponse(
        id=uuid4(),
        organization_id=uuid4(),
        lead_id=uuid4(),
        actor_id=uuid4(),
        activity_type="NOTE",
        title="Customer discussion",
        description=None,
        details={"source": "phone"},
        occurred_at=now,
        created_at=now,
    )

    assert response.activity_type == "NOTE"
    assert response.details == {"source": "phone"}


def test_list_response_defaults_to_empty_items():
    response = ActivityListResponse(items=[])

    assert response.items == []