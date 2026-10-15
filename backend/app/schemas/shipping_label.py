from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CanonicalLabelStatus = Literal[
    "CREATED",
    "PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "EXCEPTION",
    "DELIVERED",
    "RETURNED",
    "LOST_OR_DAMAGED",
]


class ShippingLabelCreate(BaseModel):
    """Input payload to register and associate a shipping label with an order (RN-07)."""

    tracking_number: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique carrier tracking number assigned to the package.",
        examples=["TRK-001-ALPHA"],
    )
    carrier_id: int = Field(
        ...,
        gt=0,
        description="Identifier of the assigned carrier.",
        examples=[1],
    )
    weight_kg: Decimal | None = Field(
        default=None,
        ge=0,
        description="Physical package weight in kilograms.",
        examples=[Decimal("2.50")],
    )
    dispatch_id: int | None = Field(
        default=None,
        gt=0,
        description="Identifier of the grouping dispatch if already consolidated.",
        examples=[None],
    )
    status: CanonicalLabelStatus = Field(
        default="CREATED",
        description="Initial canonical status of the shipping label according to RN-01.",
        examples=["CREATED"],
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip().upper()


class ShippingLabelResponse(BaseModel):
    """Output representation with canonical information of the associated shipping label (RN-07 / RN-01)."""

    model_config = ConfigDict(from_attributes=True)

    label_id: int = Field(..., description="Internal sequential ID of the shipping label.", examples=[1])
    order_id: int = Field(..., description="Associated order ID (1:N relationship).", examples=[1])
    carrier_id: int = Field(..., description="Carrier ID responsible for transit.", examples=[1])
    tracking_number: str = Field(..., description="Tracking code of the label.", examples=["TRK-001-ALPHA"])
    status: str = Field(..., description="Current canonical status of the label in logistics cycle.", examples=["CREATED"])
    weight_kg: Decimal | None = Field(default=None, description="Recorded package weight in kg.", examples=[Decimal("2.50")])
    dispatch_id: int | None = Field(default=None, description="Dispatch ID if consolidated.", examples=[None])
    created_at: datetime = Field(..., description="Date and time when the label was created.")


# Backward-compatible aliases with English naming.
ShippingLabelCreateLegacy = ShippingLabelCreate
ShippingLabelResponseLegacy = ShippingLabelResponse
ShippingLabelRead = ShippingLabelResponse
