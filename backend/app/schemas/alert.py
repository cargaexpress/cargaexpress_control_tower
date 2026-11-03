from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ShipmentAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: int
    label_id: int
    carrier_id: int
    carrier_name: str | None = None
    tracking_number: str
    alert_type: str = Field(
        description="PREVENTIVE_24H or PROLONGED_EXCEPTION",
    )
    severity: str = Field(
        description="WARNING or CRITICAL",
    )
    message: str
    hours_remaining: float | None = None
    exception_duration_hours: float | None = None
    exception_detail: str | None = None
    is_resolved: bool
    resolved_at: datetime | None = None
    resolution_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class AlertResolveRequest(BaseModel):
    resolution_notes: str = Field(
        min_length=3,
        description="Explanatory notes regarding how this risk/exception was resolved.",
    )


class AlertScanSummary(BaseModel):
    total_evaluated: int
    alerts_generated: int
    preventive_24h_alerts: int
    prolonged_exception_alerts: int
    alerts_resolved: int
