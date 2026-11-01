from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AtRiskEvaluationResult(BaseModel):
    """Result of evaluating the RN-04 at-risk business rule for an order."""

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(description="Order identifier")
    is_at_risk: bool = Field(description="True if the order meets any RN-04 at-risk condition")
    at_risk_reasons: list[str] = Field(
        default_factory=list, description="List of triggered at-risk condition descriptions"
    )
    current_status: str = Field(description="Current canonical order status")
    business_hours_remaining: float | None = Field(
        default=None,
        description="Business hours remaining until SLA deadline (None if not applicable or deadline passed)",
    )
    sla_deadline_datetime: datetime | None = Field(
        default=None, description="Calculated SLA deadline timestamp in UTC"
    )
    open_exception_duration_hours: float | None = Field(
        default=None,
        description="Duration in hours the order/label has been in unresolved EXCEPTION state",
    )
    evaluated_at: datetime = Field(description="Evaluation timestamp in UTC")
