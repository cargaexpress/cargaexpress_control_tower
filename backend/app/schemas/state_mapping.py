from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.state_mapping import CANONICAL_STATUSES


def _clean_source(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("source_status no puede estar vacío")
    return value


def _clean_canonical(value: str) -> str:
    value = value.strip().upper()
    if value not in CANONICAL_STATUSES:
        raise ValueError(f"canonical_status debe ser uno de: {', '.join(CANONICAL_STATUSES)}")
    return value


class StateMappingCreate(BaseModel):
    carrier_id: int = Field(gt=0)
    source_status: str = Field(max_length=100)
    canonical_status: str

    @field_validator("source_status")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        return _clean_source(value)

    @field_validator("canonical_status")
    @classmethod
    def _validate_canonical(cls, value: str) -> str:
        return _clean_canonical(value)


class StateMappingUpdate(BaseModel):
    source_status: str | None = Field(default=None, max_length=100)
    canonical_status: str | None = None

    @field_validator("source_status")
    @classmethod
    def _validate_source(cls, value: str | None) -> str | None:
        return None if value is None else _clean_source(value)

    @field_validator("canonical_status")
    @classmethod
    def _validate_canonical(cls, value: str | None) -> str | None:
        return None if value is None else _clean_canonical(value)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "StateMappingUpdate":
        if self.source_status is None and self.canonical_status is None:
            raise ValueError("Envía al menos source_status o canonical_status")
        return self


class StateMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mapping_id: int
    carrier_id: int
    source_status: str
    canonical_status: str
    created_at: datetime
    updated_at: datetime


class StateMappingResolved(BaseModel):
    carrier_id: int
    source_status: str
    canonical_status: str
