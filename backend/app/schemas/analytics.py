from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class EtlBatchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: int
    pipeline_name: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    records_extracted: int
    records_loaded: int
    records_rejected: int
    error_message: str | None = None


class FactShipmentSlaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fact_sla_id: int
    dispatch_date_key: int | None = None
    deadline_date_key: int | None = None
    delivery_date_key: int | None = None
    brand_key: int
    carrier_key: int
    dc_key: int
    status_key: int
    geo_key: int
    label_id: int
    order_id: int
    tracking_number: str
    brand_order_ref: str | None = None
    sla_status: str
    responsible_party: str | None = None
    freight_amount: Decimal
    sla_target_days: int
    actual_business_days: int | None = None
    delay_business_days: int
    is_sla_breached: bool
    is_at_risk: bool
    business_hours_remaining: Decimal | None = None
    etl_batch_id: int
    source_system: str


class FactFinancialPenaltyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fact_penalty_id: int
    calculation_date_key: int
    brand_key: int
    carrier_key: int
    status_key: int
    geo_key: int
    penalty_id: int
    label_id: int
    tracking_number: str
    incident_reference: str
    responsible_party: str
    delay_level: str
    calculation_status: str
    freight_amount: Decimal
    delay_business_days: int
    penalty_amount: Decimal | None = None
    is_carrier_payable: bool
    is_client_owed: bool
    etl_batch_id: int
    source_system: str


class AnalyticsKpiSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_shipments: int
    compliant_shipments: int
    breached_shipments: int
    at_risk_shipments: int
    compliance_rate_pct: Decimal
    total_freight_volume: Decimal
    total_penalties_amount: Decimal
    total_carrier_payable_penalties: Decimal
    total_etl_batches_run: int
