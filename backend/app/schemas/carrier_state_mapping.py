from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.state_mapping import CANONICAL_STATUSES


class CarrierStateMappingEntry(BaseModel):
    """Single state mapping entry for a carrier."""

    raw_status: str = Field(
        ...,
        max_length=100,
        description="Original raw status reported by the carrier.",
        examples=["En reparto"],
    )
    canonical_status: str = Field(
        ...,
        description="Standardized canonical status.",
        examples=["OUT_FOR_DELIVERY"],
    )

    @field_validator("raw_status")
    @classmethod
    def _validate_raw_status(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("raw_status cannot be empty")
        return value

    @field_validator("canonical_status")
    @classmethod
    def _validate_canonical_status(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in CANONICAL_STATUSES:
            raise ValueError(f"canonical_status must be one of: {', '.join(CANONICAL_STATUSES)}")
        return value

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "raw_status": "En reparto",
                "canonical_status": "OUT_FOR_DELIVERY",
            }
        }
    )


class CarrierStateMappingUpdate(BaseModel):
    """Payload for PUT: the complete replacement list of mappings for a carrier."""

    mappings: list[CarrierStateMappingEntry] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Collection of state mappings.",
    )

    @model_validator(mode="after")
    def _no_repeated_raw_status(self) -> "CarrierStateMappingUpdate":
        seen: set[str] = set()
        for entry in self.mappings:
            if entry.raw_status in seen:
                raise ValueError(f"repeated raw_status: {entry.raw_status!r}")
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


class CarrierStateMappingRead(BaseModel):
    """Single state mapping persisted in the database."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mapping record ID.", examples=[1])
    raw_status: str = Field(..., description="Source raw status.", examples=["En reparto"])
    canonical_status: str = Field(..., description="Normalized canonical status.", examples=["OUT_FOR_DELIVERY"])
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Date and time of last update.",
        examples=["2026-10-13T10:00:00Z"],
    )


class CarrierStateMappingResponse(BaseModel):
    """Response containing the complete set of mappings for a carrier."""

    carrier_id: int = Field(..., description="Carrier ID.", examples=[1])
    carrier_name: str = Field(..., description="Carrier trade name.", examples=["SimCarrier Alpha"])
    mappings: list[CarrierStateMappingRead] = Field(..., description="List of active mappings.")

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


# Backwards compatibility aliases
MapeoEstadoEntrada = CarrierStateMappingEntry
MapeoEstadosActualizar = CarrierStateMappingUpdate
MapeoEstadoSalida = CarrierStateMappingRead
MapeoEstadosSalida = CarrierStateMappingResponse
