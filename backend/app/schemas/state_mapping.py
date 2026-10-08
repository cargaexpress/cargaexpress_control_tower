from datetime import datetime

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
    carrier_id: int = Field(gt=0)
    raw_status: str = Field(max_length=100)
    canonical_status: str

    @field_validator("raw_status")
    @classmethod
    def _validate_raw_status(cls, value: str) -> str:
        return _clean_raw_status(value)

    @field_validator("canonical_status")
    @classmethod
    def _validate_canonical(cls, value: str) -> str:
        return _clean_canonical(value)


class StateMappingUpdate(BaseModel):
    raw_status: str | None = Field(default=None, max_length=100)
    canonical_status: str | None = None

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


class StateMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    carrier_id: int
    raw_status: str
    canonical_status: str
    created_at: datetime
    updated_at: datetime


class StateMappingResolved(BaseModel):
    carrier_id: int
    raw_status: str
    canonical_status: str
