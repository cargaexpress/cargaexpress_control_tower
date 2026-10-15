from pydantic import BaseModel, ConfigDict, Field


class HTTPErrorResponse(BaseModel):
    """Standard error response schema for the API."""

    detail: str = Field(
        ...,
        description="Detailed explanatory error message.",
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
