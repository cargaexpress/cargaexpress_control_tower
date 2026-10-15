from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CanonicalStatus = Literal[
    "CREATED",
    "PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "EXCEPTION",
    "DELIVERED",
    "RETURNED",
    "LOST_OR_DAMAGED",
]


class OrderLineCreate(BaseModel):
    """Product line or SKU item included when creating an order."""

    sku: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique product identifier (SKU).",
        examples=["SKU-SHIRT-BLUE-M"],
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="Human-readable description of the item.",
        examples=["Blue cotton shirt size M"],
    )
    quantity_ordered: int = Field(
        ...,
        gt=0,
        description="Quantity ordered for the item.",
        examples=[2],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sku": "SKU-SHIRT-BLUE-M",
                "description": "Blue cotton shirt size M",
                "quantity_ordered": 2,
            }
        }
    )


class OrderLineRead(BaseModel):
    """Representation of an order line persisted in the database."""

    model_config = ConfigDict(from_attributes=True)

    order_line_id: int = Field(..., description="Sequential ID of the order line.", examples=[101])
    order_id: int = Field(..., description="ID of the parent order.", examples=[1])
    line_number: int = Field(..., description="Ordinal line number within the order.", examples=[1])
    sku: str = Field(..., description="Unique product SKU.", examples=["SKU-SHIRT-BLUE-M"])
    description: str | None = Field(default=None, description="Item description.", examples=["Blue cotton shirt"])
    quantity_ordered: int = Field(..., description="Quantity ordered.", examples=[2])


class OrderRecipientCreate(BaseModel):
    """Recipient contact and delivery address information."""

    full_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Full name or company name of the recipient.",
        examples=["Juan Perez"],
    )
    email: str | None = Field(
        default=None,
        max_length=120,
        description="Email address for delivery notifications.",
        examples=["juan.perez@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=30,
        description="Contact phone number for delivery.",
        examples=["+573001234567"],
    )
    address_line: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="Physical delivery street address.",
        examples=["Carrera 15 # 93-47 Apto 502"],
    )
    city: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Destination city.",
        examples=["Bogota"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "full_name": "Juan Perez",
                "email": "juan.perez@example.com",
                "phone": "+573001234567",
                "address_line": "Carrera 15 # 93-47 Apto 502",
                "city": "Bogota",
            }
        }
    )


class OrderRecipientRead(BaseModel):
    """Recipient information for a queried order."""

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(..., description="Order ID.", examples=[1])
    full_name: str = Field(..., description="Recipient full name.", examples=["Juan Perez"])
    email: str | None = Field(default=None, description="Email address.", examples=["juan.perez@example.com"])
    phone: str | None = Field(default=None, description="Contact phone.", examples=["+573001234567"])
    address_line: str = Field(..., description="Delivery address.", examples=["Carrera 15 # 93-47 Apto 502"])
    city: str = Field(..., description="Destination city.", examples=["Bogota"])


class OrderCreate(BaseModel):
    """Payload to register a new order in the WMS Control Tower."""

    brand_id: int = Field(
        ...,
        gt=0,
        description="Identifier of the brand owning the inventory.",
        examples=[1],
    )
    dc_id: int = Field(
        ...,
        gt=0,
        description="Origin Distribution Center identifier.",
        examples=[1],
    )
    shipment_type_code: str = Field(
        ...,
        description="Shipment type code (STANDARD, EXPRESS, SAME_DAY).",
        examples=["STANDARD"],
    )
    brand_order_ref: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique external order reference provided by the brand.",
        examples=["ORD-MODA-2026-0001"],
    )
    destination_country: str = Field(
        default="CO",
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 destination country code.",
        examples=["CO"],
    )
    destination_region: str | None = Field(
        default=None,
        max_length=100,
        description="Department or province of delivery.",
        examples=["Cundinamarca"],
    )
    freight_value: Decimal = Field(
        ...,
        gt=0,
        description="Agreed shipping freight charge.",
        examples=[Decimal("15000.00")],
    )
    status: CanonicalStatus = Field(
        default="CREATED",
        description="Initial operational status of the order.",
        examples=["CREATED"],
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip().upper()

    order_lines: list[OrderLineCreate] = Field(
        ...,
        min_length=1,
        description="List of product items included in the order.",
    )
    recipient: OrderRecipientCreate = Field(
        ...,
        description="Detailed delivery recipient information.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "brand_id": 1,
                "dc_id": 1,
                "shipment_type_code": "STANDARD",
                "brand_order_ref": "ORD-MODA-2026-0001",
                "destination_country": "CO",
                "destination_region": "Cundinamarca",
                "freight_value": 15000.00,
                "status": "CREATED",
                "order_lines": [
                    {
                        "sku": "SKU-SHIRT-BLUE-M",
                        "description": "Blue cotton shirt size M",
                        "quantity_ordered": 2,
                    }
                ],
                "recipient": {
                    "full_name": "Juan Perez",
                    "email": "juan.perez@example.com",
                    "phone": "+573001234567",
                    "address_line": "Carrera 15 # 93-47 Apto 502",
                    "city": "Bogota",
                },
            }
        }
    )


class OrderStatusUpdate(BaseModel):
    """Payload to update an order's status."""

    status: CanonicalStatus = Field(
        ...,
        description="New operational status of the order.",
        examples=["PICKED_UP"],
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip().upper()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "PICKED_UP"
            }
        }
    )


class OrderRead(BaseModel):
    """Full detail of a queried order."""

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(..., description="Auto-generated internal order ID.", examples=[1])
    brand_id: int = Field(..., description="ID of the brand owning the order.", examples=[1])
    dc_id: int = Field(..., description="Distribution Center ID.", examples=[1])
    shipment_type_code: str = Field(..., description="Shipment type code.", examples=["STANDARD"])
    brand_order_ref: str = Field(..., description="Brand external reference.", examples=["ORD-MODA-2026-0001"])
    destination_country: str = Field(..., description="Destination country.", examples=["CO"])
    destination_region: str | None = Field(default=None, description="Region/department.", examples=["Cundinamarca"])
    freight_value: Decimal = Field(..., description="Freight charge value.", examples=[Decimal("15000.00")])
    status: str = Field(..., description="Current order status.", examples=["CREATED"])
    created_at: datetime = Field(
        ...,
        description="Order creation date and time.",
        examples=["2026-10-13T10:00:00Z"],
    )
    order_lines: list[OrderLineRead] = Field(..., description="Items associated with the order.")
    recipient: OrderRecipientRead = Field(..., description="Order recipient details.")


class OrderListResponse(BaseModel):
    """Paginated response structure for order listings."""

    items: list[OrderRead] = Field(..., description="List of orders on the current page.")
    total: int = Field(..., ge=0, description="Total count of matching orders.", examples=[100])
    skip: int = Field(..., ge=0, description="Offset applied to the query.", examples=[0])
    limit: int = Field(..., gt=0, description="Maximum number of records returned per page.", examples=[20])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [],
                "total": 0,
                "skip": 0,
                "limit": 20,
            }
        }
    )


# Backward-compatible aliases with English naming.
OrderCreateLegacy = OrderCreate
OrderReadLegacy = OrderRead
