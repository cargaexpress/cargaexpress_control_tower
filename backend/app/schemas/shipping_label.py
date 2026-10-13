from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GuiaCreate(BaseModel):
    """Esquema de entrada para la generación o registro de una guía de despacho (Shipping Label)."""

    order_id: int = Field(
        ...,
        gt=0,
        description="Identificador del pedido asociado a la guía de transporte.",
        examples=[1],
    )
    carrier_id: int = Field(
        ...,
        gt=0,
        description="Identificador de la empresa transportadora asignada.",
        examples=[1],
    )
    tracking_number: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Número de guía o código de seguimiento oficial.",
        examples=["TRK-BOG-2026-0001"],
    )
    status: str = Field(
        default="CREATED",
        description="Estado operativo inicial de la guía.",
        examples=["CREATED"],
    )
    weight_kg: Decimal | None = Field(
        default=None,
        gt=0,
        description="Peso físico del paquete en kilogramos.",
        examples=[Decimal("2.500")],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "order_id": 1,
                "carrier_id": 1,
                "tracking_number": "TRK-BOG-2026-0001",
                "status": "CREATED",
                "weight_kg": 2.500,
            }
        }
    )


class GuiaResponse(BaseModel):
    """Representación de salida de una guía de transporte (Shipping Label)."""

    model_config = ConfigDict(from_attributes=True)

    label_id: int = Field(..., description="ID secuencial interno de la guía.", examples=[1])
    order_id: int = Field(..., description="ID del pedido relacionado.", examples=[1])
    carrier_id: int = Field(..., description="ID de la transportadora.", examples=[1])
    tracking_number: str = Field(..., description="Número de tracking de la guía.", examples=["TRK-BOG-2026-0001"])
    dispatch_id: int | None = Field(default=None, description="ID del despacho en caso de estar consolidado.", examples=[None])
    status: str = Field(..., description="Estado actual de la guía en el ciclo logístico.", examples=["CREATED"])
    weight_kg: Decimal | None = Field(default=None, description="Peso del paquete en kg.", examples=[Decimal("2.500")])
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Fecha y hora de generación de la guía.",
        examples=["2026-10-13T10:00:00Z"],
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "label_id": 1,
                "order_id": 1,
                "carrier_id": 1,
                "tracking_number": "TRK-BOG-2026-0001",
                "dispatch_id": None,
                "status": "CREATED",
                "weight_kg": 2.500,
                "created_at": "2026-10-13T10:00:00Z",
            }
        },
    )


# Alias en inglés para compatibilidad
ShippingLabelCreate = GuiaCreate
ShippingLabelRead = GuiaResponse
