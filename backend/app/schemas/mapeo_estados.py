from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.state_mapping import CANONICAL_STATUSES


class MapeoEstadoEntrada(BaseModel):
    """Entrada individual de mapeo para una transportadora."""

    raw_status: str = Field(
        ...,
        max_length=100,
        description="Estado original reportado por la transportadora.",
        examples=["En reparto"],
    )
    canonical_status: str = Field(
        ...,
        description="Estado canónico homologado.",
        examples=["OUT_FOR_DELIVERY"],
    )

    @field_validator("raw_status")
    @classmethod
    def _validate_raw_status(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("raw_status no puede estar vacío")
        return value

    @field_validator("canonical_status")
    @classmethod
    def _validate_canonical_status(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in CANONICAL_STATUSES:
            raise ValueError(f"canonical_status debe ser uno de: {', '.join(CANONICAL_STATUSES)}")
        return value

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "raw_status": "En reparto",
                "canonical_status": "OUT_FOR_DELIVERY",
            }
        }
    )


class MapeoEstadosActualizar(BaseModel):
    """Cuerpo del PUT: la lista completa de mapeos que debe quedar para la transportadora."""

    mappings: list[MapeoEstadoEntrada] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Colección de equivalencias de estado.",
    )

    @model_validator(mode="after")
    def _no_repeated_raw_status(self) -> "MapeoEstadosActualizar":
        seen: set[str] = set()
        for entry in self.mappings:
            if entry.raw_status in seen:
                raise ValueError(f"raw_status repetido: {entry.raw_status!r}")
            seen.add(entry.raw_status)
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mappings": [
                    {"raw_status": "Generada", "canonical_status": "CREATED"},
                    {"raw_status": "En reparto", "canonical_status": "OUT_FOR_DELIVERY"},
                    {"raw_status": "Entregada", "canonical_status": "DELIVERED"},
                ]
            }
        }
    )


class MapeoEstadoSalida(BaseModel):
    """Mapeo individual persistido en base de datos."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="ID del registro de mapeo.", examples=[1])
    raw_status: str = Field(..., description="Estado de origen.", examples=["En reparto"])
    canonical_status: str = Field(..., description="Estado canónico homologado.", examples=["OUT_FOR_DELIVERY"])
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Fecha y hora de actualización.",
        examples=["2026-10-13T10:00:00Z"],
    )


class MapeoEstadosSalida(BaseModel):
    """Respuesta con el conjunto completo de mapeos de una transportadora."""

    carrier_id: int = Field(..., description="ID de la transportadora.", examples=[1])
    carrier_name: str = Field(..., description="Nombre comercial de la transportadora.", examples=["SimCarrier Alpha"])
    mappings: list[MapeoEstadoSalida] = Field(..., description="Lista de mapeos vigentes.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "carrier_id": 1,
                "carrier_name": "SimCarrier Alpha",
                "mappings": [
                    {
                        "id": 1,
                        "raw_status": "En reparto",
                        "canonical_status": "OUT_FOR_DELIVERY",
                        "updated_at": "2026-10-13T10:00:00Z",
                    }
                ],
            }
        }
    )
