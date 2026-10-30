
"""Tests for DealFlow deal request schemas."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.deals.schemas import DealCreateRequest, DealStage


def test_deal_create_request_accepts_valid_data() -> None:
    payload = DealCreateRequest(
        customer_profile_id=uuid4(),
        property_id=uuid4(),
        stage=DealStage.NEGOTIATION,
        expected_value="1250000.00",
        currency="inr",
        notes="  Customer requested a callback.  ",
    )

    assert payload.stage == DealStage.NEGOTIATION
    assert payload.currency == "INR"
    assert payload.notes == "Customer requested a callback."


def test_deal_create_request_defaults_to_new_stage_and_inr() -> None:
    payload = DealCreateRequest(
        customer_profile_id=uuid4(),
        property_id=uuid4(),
    )

    assert payload.stage == DealStage.NEW
    assert payload.currency == "INR"
    assert payload.lead_id is None
    assert payload.owner_user_id is None


@pytest.mark.parametrize("currency", ["IN", "INDIA", "12!", ""])
def test_deal_create_request_rejects_invalid_currency(
    currency: str,
) -> None:
    with pytest.raises(ValidationError):
        DealCreateRequest(
            customer_profile_id=uuid4(),
            property_id=uuid4(),
            currency=currency,
        )


def test_deal_create_request_rejects_negative_value() -> None:
    with pytest.raises(ValidationError):
        DealCreateRequest(
            customer_profile_id=uuid4(),
            property_id=uuid4(),
            expected_value="-1",
        )


def test_deal_create_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DealCreateRequest(
            customer_profile_id=uuid4(),
            property_id=uuid4(),
            organization_id=uuid4(),
        )


def test_deal_create_request_rejects_invalid_stage() -> None:
    with pytest.raises(ValidationError):
        DealCreateRequest(
            customer_profile_id=uuid4(),
            property_id=uuid4(),
            stage="UNRECOGNIZED_STAGE",
        )
