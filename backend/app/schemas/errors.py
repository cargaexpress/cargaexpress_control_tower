from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HTTPErrorResponse(BaseModel):
    """Standard error response schema for the API."""

    detail: str | list[dict[str, Any]] = Field(
        ...,
        description="Detailed error message or structured request-validation errors.",
        examples=["Requested resource was not found."],
    )
    error_code: str | None = Field(
        default=None,
        description="Standardized system error code.",
        examples=["RESOURCE_NOT_FOUND"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Requested resource was not found in the system.",
                "error_code": "NOT_FOUND",
            }
        }
    )
