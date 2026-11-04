from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    pass


# =============================================================================
# 1. Dimension Tables
# =============================================================================


class DimDate(Base):
    """Calendar Date Dimension (Grain: 1 row per calendar day)."""

    __tablename__ = "dim_dates"

    date_key: Mapped[int] = mapped_column(Integer, primary_key=True)  # YYYYMMDD
    calendar_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    month_name: Mapped[str] = mapped_column(String, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=Monday, 7=Sunday
    day_name: Mapped[str] = mapped_column(String, nullable=False)
    is_weekend: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_sunday: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_holiday_co: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_holiday_mx: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_holiday_pe: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DimBrand(Base):
    """Brand Dimension with Surrogate Key (Grain: 1 row per Brand)."""

    __tablename__ = "dim_brands"
    __table_args__ = (
        UniqueConstraint("brand_id", name="uq_dim_brands_brand_id"),
        Index("ix_dim_brands_brand_id", "brand_id"),
    )

    brand_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    brand_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    brand_name: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DimCarrier(Base):
    """Carrier Dimension with Surrogate Key (Grain: 1 row per Carrier)."""

    __tablename__ = "dim_carriers"
    __table_args__ = (
        UniqueConstraint("carrier_id", name="uq_dim_carriers_carrier_id"),
        Index("ix_dim_carriers_carrier_id", "carrier_id"),
    )

    carrier_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    carrier_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    carrier_name: Mapped[str] = mapped_column(String, nullable=False)
    integration_type: Mapped[str] = mapped_column(String, nullable=False)
    carrier_status: Mapped[str] = mapped_column(String, nullable=False)


class DimDistributionCenter(Base):
    """Distribution Center Dimension (Grain: 1 row per DC)."""

    __tablename__ = "dim_distribution_centers"
    __table_args__ = (
        UniqueConstraint("dc_id", name="uq_dim_distribution_centers_dc_id"),
        Index("ix_dim_distribution_centers_dc_id", "dc_id"),
    )

    dc_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dc_code: Mapped[str] = mapped_column(String, nullable=False)
    dc_name: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)
    country_code: Mapped[str] = mapped_column(String, nullable=False)


class DimShipmentStatus(Base):
    """Shipment Status Dimension (Grain: 1 row per canonical status)."""

    __tablename__ = "dim_shipment_statuses"
    __table_args__ = (UniqueConstraint("status_code", name="uq_dim_shipment_statuses_status_code"),)

    status_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status_code: Mapped[str] = mapped_column(String, nullable=False)
    status_category: Mapped[str] = mapped_column(String, nullable=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DimGeography(Base):
    """Geography Dimension (Grain: 1 row per country/region pair)."""

    __tablename__ = "dim_geographies"
    __table_args__ = (
        UniqueConstraint("country_code", "region_name", name="uq_dim_geographies_country_region"),
    )

    geo_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    country_code: Mapped[str] = mapped_column(String, nullable=False)
    region_name: Mapped[str] = mapped_column(String, nullable=False)


# =============================================================================
# 2. Fact Tables
# =============================================================================


class FactShipmentSla(Base):
    """Fact Table: Shipment SLA Compliance and Performance.

    Grain: Exactly 1 row per shipping label (label_id).
    Measures: freight_amount, sla_target_days, actual_business_days, delay_business_days,
              is_sla_breached, is_at_risk, business_hours_remaining, lead_time_hours.
    """

    __tablename__ = "fact_shipments_sla"
    __table_args__ = (
        UniqueConstraint("label_id", name="uq_fact_shipments_sla_label_id"),
        Index("ix_fact_shipments_sla_brand_key", "brand_key"),
        Index("ix_fact_shipments_sla_carrier_key", "carrier_key"),
        Index("ix_fact_shipments_sla_dispatch_date_key", "dispatch_date_key"),
        Index("ix_fact_shipments_sla_deadline_date_key", "deadline_date_key"),
    )

    fact_sla_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Dimension Foreign Keys
    dispatch_date_key: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dim_dates.date_key"), nullable=True
    )
    deadline_date_key: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dim_dates.date_key"), nullable=True
    )
    delivery_date_key: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dim_dates.date_key"), nullable=True
    )
    brand_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_brands.brand_key"), nullable=False
    )
    carrier_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_carriers.carrier_key"), nullable=False
    )
    dc_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_distribution_centers.dc_key"), nullable=False
    )
    status_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_shipment_statuses.status_key"), nullable=False
    )
    geo_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_geographies.geo_key"), nullable=False
    )

    # Degenerate Dimensions (Operational keys for traceability)
    label_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    brand_order_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    sla_status: Mapped[str] = mapped_column(String, nullable=False)  # MET, BREACHED, PENDING
    responsible_party: Mapped[str | None] = mapped_column(String, nullable=True)

    # Measures
    freight_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    sla_target_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    actual_business_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delay_business_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_at_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    business_hours_remaining: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    lead_time_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    # Lineage Metadata
    etl_batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_system: Mapped[str] = mapped_column(String, default="operational_db", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FactFinancialPenalty(Base):
    """Fact Table: Freight Financial Penalties.

    Grain: Exactly 1 row per penalty record (penalty_id).
    Measures: freight_amount, delay_business_days, penalty_percentage, base_penalty_amount,
              maximum_penalty_amount, penalty_amount, is_carrier_payable, is_client_owed.
    """

    __tablename__ = "fact_financial_penalties"
    __table_args__ = (
        UniqueConstraint("penalty_id", name="uq_fact_financial_penalties_penalty_id"),
        Index("ix_fact_financial_penalties_brand_key", "brand_key"),
        Index("ix_fact_financial_penalties_carrier_key", "carrier_key"),
        Index("ix_fact_financial_penalties_date_key", "calculation_date_key"),
    )

    fact_penalty_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Dimension Foreign Keys
    calculation_date_key: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_dates.date_key"), nullable=False
    )
    brand_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_brands.brand_key"), nullable=False
    )
    carrier_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_carriers.carrier_key"), nullable=False
    )
    status_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_shipment_statuses.status_key"), nullable=False
    )
    geo_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_geographies.geo_key"), nullable=False
    )

    # Degenerate Dimensions
    penalty_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    incident_reference: Mapped[str] = mapped_column(String, nullable=False)
    responsible_party: Mapped[str] = mapped_column(String, nullable=False)
    delay_level: Mapped[str] = mapped_column(String, nullable=False)
    calculation_status: Mapped[str] = mapped_column(String, nullable=False)
    contract_rule_applied: Mapped[str] = mapped_column(String, nullable=False)

    # Measures
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delay_business_days: Mapped[int] = mapped_column(Integer, nullable=False)
    penalty_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    base_penalty_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    maximum_penalty_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    penalty_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    is_carrier_payable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_client_owed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Lineage Metadata
    etl_batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_system: Mapped[str] = mapped_column(String, default="operational_db", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FactShipmentEvent(Base):
    """Fact Table: Shipment Tracking Events and Exceptions.

    Grain: Exactly 1 row per tracking anomaly/exception event (anomaly_id).
    Measures: is_resolved.
    """

    __tablename__ = "fact_shipment_events"
    __table_args__ = (
        UniqueConstraint("anomaly_id", name="uq_fact_shipment_events_anomaly_id"),
        Index("ix_fact_shipment_events_event_date_key", "event_date_key"),
        Index("ix_fact_shipment_events_carrier_key", "carrier_key"),
    )

    fact_event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Dimension Foreign Keys
    event_date_key: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_dates.date_key"), nullable=False
    )
    brand_key: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dim_brands.brand_key"), nullable=True
    )
    carrier_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_carriers.carrier_key"), nullable=False
    )
    status_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_shipment_statuses.status_key"), nullable=False
    )

    # Degenerate Dimensions
    anomaly_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tracking_number: Mapped[str] = mapped_column(String, nullable=False)
    raw_status: Mapped[str] = mapped_column(String, nullable=False)
    canonical_status: Mapped[str] = mapped_column(String, nullable=False)
    anomaly_type: Mapped[str | None] = mapped_column(String, nullable=True)

    # Lineage Metadata
    etl_batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_system: Mapped[str] = mapped_column(String, default="operational_db", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FactCarrierSettlement(Base):
    """Fact Table: Carrier Biweekly Settlements.

    Grain: Exactly 1 row per carrier settlement period (settlement_id).
    Measures: total_penalties_count, total_freight_amount, total_owed_to_clients,
              total_recoverable_from_carrier, net_settlement_amount.
    """

    __tablename__ = "fact_carrier_settlements"
    __table_args__ = (
        UniqueConstraint("settlement_id", name="uq_fact_carrier_settlements_settlement_id"),
        Index("ix_fact_carrier_settlements_carrier_key", "carrier_key"),
    )

    fact_settlement_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )

    period_start_date_key: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_dates.date_key"), nullable=False
    )
    period_end_date_key: Mapped[int] = mapped_column(
        Integer, ForeignKey("dim_dates.date_key"), nullable=False
    )
    carrier_key: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_carriers.carrier_key"), nullable=False
    )

    settlement_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_code: Mapped[str] = mapped_column(String, nullable=False)
    settlement_status: Mapped[str] = mapped_column(String, nullable=False)

    total_penalties_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_freight_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_owed_to_clients: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_recoverable_from_carrier: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    net_settlement_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    etl_batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_system: Mapped[str] = mapped_column(String, default="operational_db", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# =============================================================================
# 3. Data Lineage and Data Quality Audit Tables
# =============================================================================


class EtlBatchRun(Base):
    """Records ETL/ELT pipeline executions for end-to-end data lineage and auditability."""

    __tablename__ = "etl_batch_runs"

    batch_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_name: Mapped[str] = mapped_column(
        String, default="operational_to_olap_sync", nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String, default="RUNNING", nullable=False
    )  # RUNNING, COMPLETED, FAILED
    records_extracted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_loaded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    rejected_records: Mapped[list["EtlRejectedRecord"]] = relationship(back_populates="batch")


class EtlRejectedRecord(Base):
    """Preserves rejected records during data transformation and cleaning with rejection reasons."""

    __tablename__ = "etl_rejected_records"

    rejection_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("etl_batch_runs.batch_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_table: Mapped[str] = mapped_column(String, nullable=False)
    source_record_id: Mapped[str] = mapped_column(String, nullable=False)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    batch: Mapped["EtlBatchRun"] = relationship(back_populates="rejected_records")
