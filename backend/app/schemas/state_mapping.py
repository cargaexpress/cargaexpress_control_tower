from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.state_mapping import CANONICAL_STATUSES


def clean_raw_status(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("raw_status cannot be empty")
    return value


def clean_canonical_status(value: str) -> str:
    value = value.strip().upper()
    if value not in CANONICAL_STATUSES:
        raise ValueError(f"canonical_status must be one of: {', '.join(CANONICAL_STATUSES)}")
    return value


_clean_raw_status = clean_raw_status
_clean_canonical = clean_canonical_status


class StateMappingCreate(BaseModel):
    """Payload to create a new mapping from a carrier status to a canonical status."""

    carrier_id: int = Field(
        ...,
        gt=0,
        description="Identifier of the carrier to map.",
        examples=[1],
    )
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
    """Payload for partial update of an existing state mapping."""

    raw_status: str | None = Field(
        default=None,
        max_length=100,
        description="New value for the carrier's raw status.",
        examples=["En ruta de entrega"],
    )
    canonical_status: str | None = Field(
        default=None,
        description="New canonical status.",
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
            raise ValueError("Provide at least raw_status or canonical_status")
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
    """Persisted state mapping entity with traceability."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mapping record ID.", examples=[1])
    carrier_id: int = Field(..., description="Associated carrier ID.", examples=[1])
    raw_status: str = Field(..., description="Source raw status.", examples=["En reparto"])
    canonical_status: str = Field(
        ..., description="Standardized canonical status.", examples=["OUT_FOR_DELIVERY"]
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Record creation date and time.",
        examples=["2026-10-13T10:00:00Z"],
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Date and time of last update.",
        examples=["2026-10-13T10:00:00Z"],
    )


class StateMappingResolved(BaseModel):
    """Result of resolving or translating a carrier raw status."""

    carrier_id: int = Field(..., description="Queried carrier ID.", examples=[1])
    raw_status: str = Field(..., description="Received raw status.", examples=["En reparto"])
    canonical_status: str = Field(
        ...,
        description="Corresponding canonical status from active mapping.",
        examples=["OUT_FOR_DELIVERY"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "carrier_id": 1,
                "raw_status": "En reparto",
                "canonical_status": "OUT_FOR_DELIVERY",
            }
        }
    )
