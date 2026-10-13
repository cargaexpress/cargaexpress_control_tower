from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.state_mapping import CANONICAL_STATUSES


def _clean_raw_status(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("raw_status no puede estar vacío")
    return value


def _clean_canonical(value: str) -> str:
    value = value.strip().upper()
    if value not in CANONICAL_STATUSES:
        raise ValueError(f"canonical_status debe ser uno de: {', '.join(CANONICAL_STATUSES)}")
    return value


class StateMappingCreate(BaseModel):
    """Payload para crear un nuevo mapeo de estado de transportadora a estado canónico."""

    carrier_id: int = Field(
        ...,
        gt=0,
        description="Identificador de la transportadora a mapear.",
        examples=[1],
    )
    raw_status: str = Field(
        ...,
        max_length=100,
        description="Estado original reportado por la transportadora.",
        examples=["En reparto"],
    )
    canonical_status: str = Field(
        ...,
        description="Estado canónico normalizado.",
        examples=["OUT_FOR_DELIVERY"],
    )

    @field_validator("raw_status")
    @classmethod
    def _validate_raw_status(cls, value: str) -> str:
        return _clean_raw_status(value)

    @field_validator("canonical_status")
    @classmethod
    def _validate_canonical(cls, value: str) -> str:
        return _clean_canonical(value)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "carrier_id": 1,
                "raw_status": "En reparto",
                "canonical_status": "OUT_FOR_DELIVERY",
            }
        }
    )


class StateMappingUpdate(BaseModel):
    """Payload para actualización parcial de un mapeo de estado existente."""

    raw_status: str | None = Field(
        default=None,
        max_length=100,
        description="Nuevo valor del estado original de la transportadora.",
        examples=["En ruta de entrega"],
    )
    canonical_status: str | None = Field(
        default=None,
        description="Nuevo estado canónico homologado.",
        examples=["OUT_FOR_DELIVERY"],
    )

    @field_validator("raw_status")
    @classmethod
    def _validate_raw_status(cls, value: str | None) -> str | None:
        return None if value is None else _clean_raw_status(value)

    @field_validator("canonical_status")
    @classmethod
    def _validate_canonical(cls, value: str | None) -> str | None:
        return None if value is None else _clean_canonical(value)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "StateMappingUpdate":
        if self.raw_status is None and self.canonical_status is None:
            raise ValueError("Envía al menos raw_status o canonical_status")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "raw_status": "En ruta de entrega",
                "canonical_status": "OUT_FOR_DELIVERY",
            }
        }
    )


class StateMappingRead(BaseModel):
    """Entidad persistida del mapeo de estado con trazabilidad."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="ID secuencial del mapeo.", examples=[1])
    carrier_id: int = Field(..., description="ID de la transportadora asociada.", examples=[1])
    raw_status: str = Field(..., description="Estado crudo de origen.", examples=["En reparto"])
    canonical_status: str = Field(..., description="Estado canónico normalizado.", examples=["OUT_FOR_DELIVERY"])
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Fecha y hora de creación del registro.",
        examples=["2026-10-13T10:00:00Z"],
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Fecha y hora de la última modificación.",
        examples=["2026-10-13T10:00:00Z"],
    )


class StateMappingResolved(BaseModel):
    """Resultado de la resolución o traducción de un estado recibido de transportadora."""

    carrier_id: int = Field(..., description="ID de la transportadora consultada.", examples=[1])
    raw_status: str = Field(..., description="Estado crudo recibido.", examples=["En reparto"])
    canonical_status: str = Field(..., description="Estado canónico correspondiente según la tabla activa.", examples=["OUT_FOR_DELIVERY"])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "carrier_id": 1,
                "raw_status": "En reparto",
                "canonical_status": "OUT_FOR_DELIVERY",
            }
        }
    )
