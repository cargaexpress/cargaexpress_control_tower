from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    status: str = Field(
        default="CREADO",
        description="Initial canonical status of the shipping label according to RN-01.",
        examples=["CREADO"],
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional initial metadata for the label.",
    )


class ShippingLabelResponse(BaseModel):
    """Output representation with canonical information of the associated shipping label (RN-07 / RN-01)."""

    model_config = ConfigDict(from_attributes=True)

    label_id: int = Field(..., description="Internal sequential ID of the shipping label.", examples=[1])
    order_id: int = Field(..., description="Associated order ID (1:N relationship).", examples=[1])
    carrier_id: int = Field(..., description="Carrier ID responsible for transit.", examples=[1])
    tracking_number: str = Field(..., description="Tracking code of the label.", examples=["TRK-001-ALPHA"])
    status: str = Field(..., description="Current canonical status of the label in logistics cycle.", examples=["CREADO"])
    weight_kg: Decimal | None = Field(default=None, description="Recorded package weight in kg.", examples=[Decimal("2.50")])
    dispatch_id: int | None = Field(default=None, description="Dispatch ID if consolidated.", examples=[None])
    created_at: datetime = Field(..., description="Date and time when the label was created.")


# Backwards compatibility aliases
GuiaCreate = ShippingLabelCreate
GuiaResponse = ShippingLabelResponse
ShippingLabelRead = ShippingLabelResponse
