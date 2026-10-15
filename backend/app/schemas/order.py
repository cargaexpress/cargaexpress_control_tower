from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderLineCreate(BaseModel):
    """Línea de producto o SKU incluida en la creación del pedido."""

    sku: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Código único de producto (SKU).",
        examples=["SKU-SHIRT-BLUE-M"],
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="Descripción legible del artículo.",
        examples=["Camiseta de algodón azul talla M"],
    )
    quantity_ordered: int = Field(
        ...,
        gt=0,
        description="Cantidad requerida del artículo.",
        examples=[2],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sku": "SKU-SHIRT-BLUE-M",
                "description": "Camiseta de algodón azul talla M",
                "quantity_ordered": 2,
            }
        }
    )


class OrderLineRead(BaseModel):
    """Representación de una línea de producto persistida en el pedido."""

    model_config = ConfigDict(from_attributes=True)

    order_line_id: int = Field(..., description="ID secuencial de la línea de pedido.", examples=[101])
    order_id: int = Field(..., description="ID del pedido al que pertenece.", examples=[1])
    line_number: int = Field(..., description="Número ordinal de la línea dentro del pedido.", examples=[1])
    sku: str = Field(..., description="Código único de producto (SKU).", examples=["SKU-SHIRT-BLUE-M"])
    description: str | None = Field(default=None, description="Descripción del artículo.", examples=["Camiseta de algodón azul"])
    quantity_ordered: int = Field(..., description="Cantidad ordenada.", examples=[2])


class OrderRecipientCreate(BaseModel):
    """Datos de contacto y entrega del destinatario."""

    full_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Nombre completo o razón social del destinatario.",
        examples=["Juan Pérez Rodríguez"],
    )
    email: str | None = Field(
        default=None,
        max_length=120,
        description="Correo electrónico para notificaciones de entrega.",
        examples=["juan.perez@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=30,
        description="Teléfono de contacto para la entrega.",
        examples=["+573001234567"],
    )
    address_line: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="Dirección de entrega física.",
        examples=["Carrera 15 # 93-47 Apto 502"],
    )
    city: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Ciudad de destino.",
        examples=["Bogotá D.C."],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "full_name": "Juan Pérez Rodríguez",
                "email": "juan.perez@example.com",
                "phone": "+573001234567",
                "address_line": "Carrera 15 # 93-47 Apto 502",
                "city": "Bogotá D.C.",
            }
        }
    )


class OrderRecipientRead(BaseModel):
    """Datos del destinatario de una orden consultada."""

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(..., description="ID del pedido.", examples=[1])
    full_name: str = Field(..., description="Nombre del destinatario.", examples=["Juan Pérez Rodríguez"])
    email: str | None = Field(default=None, description="Correo electrónico.", examples=["juan.perez@example.com"])
    phone: str | None = Field(default=None, description="Teléfono de contacto.", examples=["+573001234567"])
    address_line: str = Field(..., description="Dirección de entrega.", examples=["Carrera 15 # 93-47 Apto 502"])
    city: str = Field(..., description="Ciudad de destino.", examples=["Bogotá D.C."])


class OrderCreate(BaseModel):
    """Payload para registrar una nueva orden en la Torre de Control WMS."""

    brand_id: int = Field(
        ...,
        gt=0,
        description="Identificador de la marca dueña del inventario.",
        examples=[1],
    )
    dc_id: int = Field(
        ...,
        gt=0,
        description="Identificador del Centro de Distribución de origen.",
        examples=[1],
    )
    shipment_type_code: str = Field(
        ...,
        description="Código del tipo de despacho acordado (STANDARD, EXPRESS, SAME_DAY).",
        examples=["STANDARD"],
    )
    brand_order_ref: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Referencia única o número de pedido externo de la marca.",
        examples=["ORD-MODA-2026-0001"],
    )
    destination_country: str = Field(
        default="CO",
        min_length=2,
        max_length=2,
        description="Código ISO 3166-1 alpha-2 del país destino.",
        examples=["CO"],
    )
    destination_region: str | None = Field(
        default=None,
        max_length=100,
        description="Departamento o provincia de entrega.",
        examples=["Cundinamarca"],
    )
    freight_value: Decimal = Field(
        ...,
        gt=0,
        description="Valor acordado del flete de envío.",
        examples=[Decimal("15000.00")],
    )
    status: str = Field(
        default="CREATED",
        description="Estado operativo inicial de la orden.",
        examples=["CREATED"],
    )
    order_lines: list[OrderLineCreate] = Field(
        ...,
        min_length=1,
        description="Lista de ítems incluidos en la orden de despacho.",
    )
    recipient: OrderRecipientCreate = Field(
        ...,
        description="Información detallada del destinatario de la entrega.",
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
                        "description": "Camiseta de algodón azul talla M",
                        "quantity_ordered": 2,
                    }
                ],
                "recipient": {
                    "full_name": "Juan Pérez Rodríguez",
                    "email": "juan.perez@example.com",
                    "phone": "+573001234567",
                    "address_line": "Carrera 15 # 93-47 Apto 502",
                    "city": "Bogotá D.C.",
                },
            }
        }
    )


class OrderStatusUpdate(BaseModel):
    """Payload para actualizar el estado de una orden."""

    status: str = Field(
        ...,
        description="Nuevo estado operativo de la orden.",
        examples=["PICKED_UP"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "PICKED_UP"
            }
        }
    )


class OrderRead(BaseModel):
    """Detalle completo de una orden consultada en el sistema."""

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(..., description="ID interno autogenerado de la orden.", examples=[1])
    brand_id: int = Field(..., description="ID de la marca dueña de la orden.", examples=[1])
    dc_id: int = Field(..., description="ID del Centro de Distribución.", examples=[1])
    shipment_type_code: str = Field(..., description="Tipo de envío.", examples=["STANDARD"])
    brand_order_ref: str = Field(..., description="Referencia de la marca.", examples=["ORD-MODA-2026-0001"])
    destination_country: str = Field(..., description="País destino.", examples=["CO"])
    destination_region: str | None = Field(default=None, description="Región/departamento.", examples=["Cundinamarca"])
    freight_value: Decimal = Field(..., description="Valor del flete.", examples=[Decimal("15000.00")])
    status: str = Field(..., description="Estado actual de la orden.", examples=["CREATED"])
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Fecha y hora de creación de la orden.",
        examples=["2026-10-13T10:00:00Z"],
    )
    order_lines: list[OrderLineRead] = Field(..., description="Ítems asociados a la orden.")
    recipient: OrderRecipientRead = Field(..., description="Destinatario de la orden.")


class OrderListResponse(BaseModel):
    """Estructura de respuesta paginada para el listado de pedidos."""

    items: list[OrderRead] = Field(..., description="Listado de pedidos pertenecientes a la página actual.")
    total: int = Field(..., ge=0, description="Cantidad total de pedidos registrados.", examples=[100])
    skip: int = Field(..., ge=0, description="Desplazamiento u offset aplicado en la consulta.", examples=[0])
    limit: int = Field(..., gt=0, description="Límite de registros retornados por página.", examples=[20])

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


# Alias según nomenclatura en español del entregable
PedidoCreate = OrderCreate
PedidoResponse = OrderRead
