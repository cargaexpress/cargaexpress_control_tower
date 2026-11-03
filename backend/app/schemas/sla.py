from datetime import date, datetime
from decimal import Decimal

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


# =============================================================================
# Work Package 1: Brand & Carrier SLA and Penalty Query Schemas
# =============================================================================


class BrandSlaMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    brand_id: int
    total_shipments: int
    delivered_shipments: int
    compliant_shipments: int
    breached_shipments: int
    at_risk_shipments: int
    delayed_shipments: int
    compliance_rate_pct: Decimal
    total_penalties_amount: Decimal
    approved_penalties_amount: Decimal
    pending_penalties_count: int


class CarrierSlaMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    carrier_id: int
    total_shipments: int
    delivered_shipments: int
    compliant_shipments: int
    breached_shipments: int
    at_risk_shipments: int
    delayed_shipments: int
    compliance_rate_pct: Decimal
    carrier_payable_penalties_amount: Decimal
    pending_penalties_count: int


class ShipmentSlaSummaryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label_id: int
    order_id: int
    tracking_number: str
    brand_id: int
    carrier_id: int
    carrier_name: str | None = None
    brand_order_ref: str | None = None
    status: str
    dispatched_at: datetime | None = None
    deadline_utc: datetime | None = None
    delivered_at: datetime | None = None
    sla_status: str
    is_at_risk: bool = False
    delay_business_days: int = 0
    delay_level: str = "NO_DELAY"
    responsible_party: str | None = None
    penalty_amount: Decimal | None = None
    calculation_status: str | None = None
    is_carrier_payable: bool = False


class PaginatedShipmentsSlaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[ShipmentSlaSummaryItem]
    total: int
    limit: int
    offset: int


class HistoricalSlaItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_date: date
    total_shipments: int
    compliant_shipments: int
    breached_shipments: int
    compliance_rate_pct: Decimal
    total_penalties_amount: Decimal


class HistoricalSlaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    periods: list[HistoricalSlaItem]
