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
