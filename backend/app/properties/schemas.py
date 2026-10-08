from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROPERTY_TRANSACTION_TYPES = ("SALE", "RENT", "LEASE")
PROPERTY_TYPES = (
    "APARTMENT",
    "VILLA",
    "INDEPENDENT_HOUSE",
    "PLOT",
    "COMMERCIAL",
    "OTHER",
)
PROPERTY_STATUSES = (
    "AVAILABLE",
    "RESERVED",
    "SOLD",
    "RENTED",
    "LEASED",
    "UNAVAILABLE",
)


class PropertyCreateRequest(BaseModel):
    pass


class PropertyCommercialUpdateRequest(BaseModel):
    transaction_type: Literal["SALE", "RENT", "LEASE"]
    price: Decimal | None = Field(default=None, ge=0)
    currency: str
    rent: Decimal | None = Field(default=None, ge=0)
    security_deposit: Decimal | None = Field(default=None, ge=0)
    maintenance_charge: Decimal | None = Field(default=None, ge=0)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.strip().upper()

        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a valid 3-letter currency code.")

        return normalized


class PropertyLocationAttributesUpdateRequest(BaseModel):
    address_line_1: str | None = None
    address_line_2: str | None = None
    locality: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    property_type: Literal[
        "APARTMENT",
        "VILLA",
        "INDEPENDENT_HOUSE",
        "PLOT",
        "COMMERCIAL",
        "OTHER",
    ] | None = None
    bhk: int | None = Field(default=None, gt=0)
    built_up_area: Decimal | None = Field(default=None, ge=0)
    carpet_area: Decimal | None = Field(default=None, ge=0)
    floor_number: int | None = Field(default=None, ge=0)
    total_floors: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_floor_relationship(self):
        if (
            self.floor_number is not None
            and self.total_floors is not None
            and self.floor_number > self.total_floors
        ):
            raise ValueError(
                "Floor number cannot be greater than total floors."
            )

        return self


class PropertyStatusUpdateRequest(BaseModel):
    status: Literal[
        "AVAILABLE",
        "RESERVED",
        "SOLD",
        "RENTED",
        "LEASED",
        "UNAVAILABLE",
    ]


class PropertyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    created_at: object
    updated_at: object


class PropertyAssociationUpdateRequest(BaseModel):
    """Partially update Property source and owner associations."""

    source_contact_id: UUID | None = None
    owner_contact_id: UUID | None = None


class PropertyCommercialResponse(PropertyResponse):
    transaction_type: str | None
    price: Decimal | None
    currency: str | None
    rent: Decimal | None
    security_deposit: Decimal | None
    maintenance_charge: Decimal | None


class PropertyLocationAttributesResponse(PropertyResponse):
    address_line_1: str | None
    address_line_2: str | None
    locality: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    property_type: str | None
    bhk: int | None
    built_up_area: Decimal | None
    carpet_area: Decimal | None
    floor_number: int | None
    total_floors: int | None


class PropertyStatusResponse(PropertyResponse):
    status: str | None


class PropertyAssociationResponse(PropertyResponse):
    """Return Property source and owner association identifiers."""

    source_contact_id: UUID | None
    owner_contact_id: UUID | None


class PropertySearchQuery(BaseModel):
    q: str | None = None

    transaction_type: Literal["SALE", "RENT", "LEASE"] | None = None
    status: Literal[
        "AVAILABLE",
        "RESERVED",
        "SOLD",
        "RENTED",
        "LEASED",
        "UNAVAILABLE",
    ] | None = None
    property_type: Literal[
        "APARTMENT",
        "VILLA",
        "INDEPENDENT_HOUSE",
        "PLOT",
        "COMMERCIAL",
        "OTHER",
    ] | None = None

    bhk: int | None = Field(default=None, gt=0)

    city: str | None = None
    state: str | None = None
    locality: str | None = None
    postal_code: str | None = None

    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)

    min_rent: Decimal | None = Field(default=None, ge=0)
    max_rent: Decimal | None = Field(default=None, ge=0)

    min_built_up_area: Decimal | None = Field(default=None, ge=0)
    max_built_up_area: Decimal | None = Field(default=None, ge=0)

    min_carpet_area: Decimal | None = Field(default=None, ge=0)
    max_carpet_area: Decimal | None = Field(default=None, ge=0)

    floor_number: int | None = Field(default=None, ge=0)
    total_floors: int | None = Field(default=None, gt=0)

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator(
        "q",
        "city",
        "state",
        "locality",
        "postal_code",
        mode="before",
    )
    @classmethod
    def normalize_text_filters(cls, value):
        if value is None:
            return None

        normalized = str(value).strip()

        return normalized or None


class PropertySearchResult(PropertyResponse):
    status: str | None

    transaction_type: str | None
    price: Decimal | None
    currency: str | None
    rent: Decimal | None
    security_deposit: Decimal | None
    maintenance_charge: Decimal | None

    address_line_1: str | None
    address_line_2: str | None
    locality: str | None
    city: str | None
    state: str | None
    postal_code: str | None

    property_type: str | None
    bhk: int | None
    built_up_area: Decimal | None
    carpet_area: Decimal | None
    floor_number: int | None
    total_floors: int | None


class PropertySearchResponse(BaseModel):
    items: list[PropertySearchResult]
    page: int
    page_size: int
    total: int
    total_pages: int