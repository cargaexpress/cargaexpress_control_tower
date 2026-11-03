from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class HolidayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    holiday_id: int
    country_code: str
    holiday_date: date
    name: str
    year: int
    is_national: bool


class SlaCalculationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tracking_number: str
    destination_country: str
    shipment_type_code: str
    sla_business_days: int
    dispatched_at: datetime | None = None
    sla_start_date: date | None = None
    deadline_utc: datetime | None = None
    delivered_at: datetime | None = None
    is_at_risk: bool = False
    risk_reason: str | None = None
    business_hours_remaining: float | None = None
    exception_open_duration_hours: float | None = None
    sla_status: str = Field(
        default="PENDING",
        description="Compliance status: PENDING, MET (on time), BREACHED (late).",
    )
    responsible_party: str | None = None


class SlaTrackingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    brand_order_ref: str
    destination_country: str
    shipment_type_code: str
    labels_sla: list[SlaCalculationResult]
    overall_order_compliant: bool = True
    overall_at_risk: bool = False
