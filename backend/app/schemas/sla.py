from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PublicHoliday(BaseModel):
    """Public holiday representation from Nager.Date API (source F6)."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    local_name: str
    name: str
    country_code: str
    fixed: bool = True
    global_holiday: bool = True


class SLADeadlineResult(BaseModel):
    """Result of SLA business-day deadline calculation (RN-03)."""

    model_config = ConfigDict(from_attributes=True)

    dispatched_at: datetime = Field(description="Order dispatch timestamp in UTC")
    sla_business_days: int = Field(description="Target delivery timeframe in business days")
    destination_country: str = Field(description="ISO-3166-1 alpha-2 destination country code")
    origin_country: str | None = Field(
        default=None, description="ISO-3166-1 alpha-2 DC origin country code"
    )
    cutoff_hour: int = Field(default=16, description="Cutoff hour (16:00 / 4:00 PM)")
    is_after_cutoff: bool = Field(
        description="True if dispatch occurred at or after 16:00 in relevant timezone"
    )
    counting_start_date: date = Field(description="Day 0 when business day counting begins")
    deadline_date: date = Field(description="Calculated SLA deadline calendar date")
    deadline_datetime: datetime = Field(
        description="Calculated SLA deadline timestamp (end of business day in UTC)"
    )
    business_days_counted: list[date] = Field(
        default_factory=list, description="List of calendar dates counted as business days"
    )
    excluded_dates: list[date] = Field(
        default_factory=list,
        description="List of dates skipped during counting (Sundays or holidays)",
    )


class SLACalculationRequest(BaseModel):
    """Payload to request SLA deadline calculation."""

    dispatched_at: datetime
    sla_business_days: int = Field(default=2, ge=0)
    destination_country: str = Field(default="CO", min_length=2, max_length=2)
    origin_country: str | None = Field(default=None, min_length=2, max_length=2)


class OrderSLAResponse(BaseModel):
    """SLA calculation, deadline breakdown, and compliance status for an order."""

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(description="Internal unique order identifier", examples=[1])
    brand_id: int = Field(description="Identifier of the brand owning the order", examples=[1])
    status: str = Field(
        description="Current canonical status of the order", examples=["IN_TRANSIT"]
    )
    destination_country: str = Field(
        description="ISO 3166-1 alpha-2 destination country code", examples=["CO"]
    )
    sla_business_days: int = Field(
        description="Target timeframe in business days under RN-03", examples=[2]
    )
    dispatched_at: datetime = Field(description="Order dispatch timestamp in UTC")
    cutoff_hour: int = Field(default=16, description="Cutoff hour threshold (16:00 / 4:00 PM)")
    is_after_cutoff: bool = Field(
        description="True if dispatch occurred at or after 16:00 in origin/destination timezone"
    )
    counting_start_date: date = Field(description="Date when business-day counting begins (Day 0)")
    deadline_date: date = Field(description="Calculated SLA deadline calendar date")
    deadline_datetime: datetime = Field(description="Calculated SLA deadline timestamp in UTC")
    business_days_counted: list[date] = Field(
        default_factory=list, description="Calendar dates counted as business days towards SLA"
    )
    excluded_dates: list[date] = Field(
        default_factory=list,
        description="Calendar dates skipped during counting (Sundays and public holidays)",
    )
    compliance_status: str = Field(
        description="Current SLA compliance status: MET, MISSED, or PENDING", examples=["PENDING"]
    )
    is_compliant: bool | None = Field(
        default=None,
        description="True if delivered within deadline, False if missed, None if pending in progress",
    )
    is_at_risk: bool = Field(
        description="True if order meets any RN-04 at-risk condition", examples=[False]
    )
    at_risk_reason: str | None = Field(
        default=None, description="Formatted summary of triggered at-risk condition"
    )
    at_risk_reasons: list[str] = Field(
        default_factory=list, description="List of all triggered at-risk condition descriptions"
    )
    business_hours_remaining: float | None = Field(
        default=None,
        description="Business hours remaining until SLA deadline (None if terminal)",
        examples=[14.0],
    )
