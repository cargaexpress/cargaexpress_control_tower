from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AttributionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attribution_id: int
    label_id: int
    order_id: int
    carrier_id: int
    tracking_number: str
    responsible_party: str = Field(
        description="DISTRIBUTION_CENTER, CARRIER, CLIENT, or UNDETERMINED"
    )
    incident_type: str
    reason: str
    evidence_details: str | None = None
    order_created_at: datetime
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    sla_deadline: datetime | None = None
    created_at: datetime


class FreightPenaltyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    penalty_id: int
    label_id: int
    order_id: int
    carrier_id: int
    brand_id: int
    settlement_id: int | None = None
    tracking_number: str
    incident_reference: str
    responsible_party: str
    freight_amount: Decimal
    delay_business_days: int
    delay_level: str
    calculation_status: str
    penalty_percentage: Decimal | None = None
    base_penalty_amount: Decimal | None = None
    maximum_penalty_amount: Decimal | None = None
    penalty_amount: Decimal | None = None
    is_carrier_payable: bool
    is_client_owed: bool
    contract_rule_applied: str
    calculated_at: datetime


class FinancialSettlementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    settlement_id: int
    carrier_id: int
    period_code: str
    period_start_date: date
    period_end_date: date
    total_penalties_count: int
    total_freight_amount: Decimal
    total_owed_to_clients: Decimal
    total_recoverable_from_carrier: Decimal
    net_settlement_amount: Decimal | None = None
    status: str
    notes: str | None = None
    created_at: datetime
    closed_at: datetime | None = None


class UniversalPenaltyConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    config_id: int
    version: str
    delay_level: str
    min_delay_days: int | None = None
    max_delay_days: int | None = None
    penalty_percentage: Decimal | None = None
    maximum_cap_percentage: Decimal | None = None
    effective_date: date
    is_active: bool
    approval_status: str
    created_at: datetime
    updated_at: datetime


class UniversalPenaltyConfigCreate(BaseModel):
    version: str = "v1.0"
    delay_level: str = Field(description="NO_DELAY, LOW, MODERATE, HIGH, CRITICAL")
    min_delay_days: int | None = None
    max_delay_days: int | None = None
    penalty_percentage: Decimal | None = None
    maximum_cap_percentage: Decimal | None = None
    effective_date: date
    is_active: bool = True
    approval_status: str = "PENDING_APPROVAL"


class UniversalPenaltyConfigUpdate(BaseModel):
    min_delay_days: int | None = None
    max_delay_days: int | None = None
    penalty_percentage: Decimal | None = None
    maximum_cap_percentage: Decimal | None = None
    effective_date: date | None = None
    is_active: bool | None = None
    approval_status: str | None = None


class SettlementGenerateRequest(BaseModel):
    carrier_id: int
    year: int
    month: int
    half: int = Field(ge=1, le=2, description="1 for H1 (1-15), 2 for H2 (16-end of month)")
    notes: str | None = None


class FinancialLedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_id: int
    settlement_id: int
    carrier_id: int
    brand_id: int | None = None
    penalty_id: int | None = None
    entry_type: str
    amount: Decimal
    currency: str
    description: str
    created_at: datetime
