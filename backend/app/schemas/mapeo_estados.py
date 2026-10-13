from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.state_mapping import CANONICAL_STATUSES


# Entrada: cada estado que reporta la transportadora y el estado canónico al que se traduce.
class MapeoEstadoEntrada(BaseModel):
    raw_status: str = Field(max_length=100)
    canonical_status: str

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


class MapeoEstadosActualizar(BaseModel):
    """Cuerpo del PUT: la lista COMPLETA de mapeos que debe quedar para la transportadora."""

    mappings: list[MapeoEstadoEntrada] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _no_repeated_raw_status(self) -> "MapeoEstadosActualizar":
        seen: set[str] = set()
        for entry in self.mappings:
            if entry.raw_status in seen:
                raise ValueError(f"raw_status repetido: {entry.raw_status!r}")
            seen.add(entry.raw_status)
        return self


class MapeoEstadoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_status: str
    canonical_status: str
    updated_at: datetime


class MapeoEstadosSalida(BaseModel):
    carrier_id: int
    carrier_name: str
    mappings: list[MapeoEstadoSalida]
