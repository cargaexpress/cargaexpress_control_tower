from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HTTPErrorResponse(BaseModel):
    """Esquema estándar para respuestas de error de la API."""

    detail: str = Field(..., description="Descripción detallada del error")


class GuiaCreate(BaseModel):
    """Esquema de entrada para registrar y asociar una guía a un pedido (RN-07)."""

    tracking_number: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Código de rastreo único de la guía asignado por la transportadora",
    )
    carrier_id: int = Field(
        ...,
        gt=0,
        description="Identificador de la transportadora asignada",
    )
    weight_kg: Decimal | None = Field(
        default=None,
        ge=0,
        description="Peso de la guía/paquete en kilogramos",
    )
    dispatch_id: int | None = Field(
        default=None,
        gt=0,
        description="Identificador del despacho agrupador si ya se encuentra consolidado",
    )
    status: str = Field(
        default="CREADO",
        description="Estado canónico inicial de la guía según RN-01",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Metadatos iniciales opcionales de la guía",
    )


class GuiaResponse(BaseModel):
    """Esquema de salida con la información canónica de la guía asociada (RN-07 / RN-01)."""

    model_config = ConfigDict(from_attributes=True)

    label_id: int = Field(..., description="ID autoincremental de la guía en el sistema")
    order_id: int = Field(..., description="ID del pedido asociado (relación 1:N)")
    carrier_id: int = Field(..., description="ID de la transportadora responsable")
    tracking_number: str = Field(..., description="Código de rastreo de la guía")
    status: str = Field(..., description="Estado canónico actual de la guía (RN-01)")
    weight_kg: Decimal | None = Field(default=None, description="Peso registrado en kg")
    dispatch_id: int | None = Field(default=None, description="ID del despacho si aplica")
    created_at: datetime = Field(..., description="Fecha y hora de creación de la guía")
