from pydantic import BaseModel, ConfigDict, Field


class HTTPErrorResponse(BaseModel):
    """Esquema estándar para respuestas de error de la API."""

    detail: str = Field(
        ...,
        description="Mensaje explicativo del error.",
        examples=["El recurso solicitado no fue encontrado."],
    )
    error_code: str | None = Field(
        default=None,
        description="Código de error estandarizado del sistema.",
        examples=["RESOURCE_NOT_FOUND"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "El recurso solicitado no fue encontrado en el sistema.",
                "error_code": "NOT_FOUND",
            }
        }
    )
