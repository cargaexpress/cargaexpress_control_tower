from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# Pydantic schemas validate incoming order data and shape API responses.
# Nested line and recipient models keep one order request atomic and readable.
# Los esquemas Pydantic validan pedidos recibidos y definen respuestas.
# Líneas y destinatario anidados mantienen cada pedido en una sola solicitud.
class OrderLineCreate(BaseModel):
    sku: str
    description: str | None = None
    quantity_ordered: int = Field(gt=0)


class OrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_line_id: int
    order_id: int
    line_number: int
    sku: str
    description: str | None
    quantity_ordered: int


class OrderRecipientCreate(BaseModel):
    full_name: str
    email: str | None = None
    phone: str | None = None
    address_line: str
    city: str


class OrderRecipientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    full_name: str
    email: str | None
    phone: str | None
    address_line: str
    city: str


class OrderCreate(BaseModel):
    brand_id: int
    dc_id: int
    shipment_type_code: str
    brand_order_ref: str
    destination_country: str = Field(min_length=2, max_length=2)
    destination_region: str | None = None
    freight_value: Decimal = Field(gt=0)
    status: str
    order_lines: list[OrderLineCreate] = Field(min_length=1)
    recipient: OrderRecipientCreate


class OrderStatusUpdate(BaseModel):
    status: str


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    brand_id: int
    dc_id: int
    shipment_type_code: str
    brand_order_ref: str
    destination_country: str
    destination_region: str | None
    freight_value: Decimal
    status: str
    created_at: datetime
    order_lines: list[OrderLineRead]
    recipient: OrderRecipientRead


class OrderListResponse(BaseModel):
    items: list[OrderRead]
    total: int
    skip: int
    limit: int
