"""Create analytical data model tables: dimensions, facts, and ETL lineage audit (Work Package 2)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-03 09:25:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Dimension Tables
    op.create_table(
        "dim_dates",
        sa.Column("date_key", sa.Integer(), nullable=False),
        sa.Column("calendar_date", sa.Date(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("month_name", sa.String(), nullable=False),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("day_name", sa.String(), nullable=False),
        sa.Column("is_weekend", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_sunday", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_holiday_co", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_holiday_mx", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_holiday_pe", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("date_key"),
        sa.UniqueConstraint("calendar_date"),
    )

    op.create_table(
        "dim_brands",
        sa.Column("brand_key", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("brand_name", sa.String(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("brand_key"),
        sa.UniqueConstraint("brand_id", name="uq_dim_brands_brand_id"),
    )
    op.create_index("ix_dim_brands_brand_id", "dim_brands", ["brand_id"], unique=False)

    op.create_table(
        "dim_carriers",
        sa.Column("carrier_key", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("carrier_id", sa.BigInteger(), nullable=False),
        sa.Column("carrier_name", sa.String(), nullable=False),
        sa.Column("integration_type", sa.String(), nullable=False),
        sa.Column("carrier_status", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("carrier_key"),
        sa.UniqueConstraint("carrier_id", name="uq_dim_carriers_carrier_id"),
    )
    op.create_index("ix_dim_carriers_carrier_id", "dim_carriers", ["carrier_id"], unique=False)

    op.create_table(
        "dim_distribution_centers",
        sa.Column("dc_key", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dc_id", sa.BigInteger(), nullable=False),
        sa.Column("dc_code", sa.String(), nullable=False),
        sa.Column("dc_name", sa.String(), nullable=False),
        sa.Column("city", sa.String(), nullable=False),
        sa.Column("country_code", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("dc_key"),
        sa.UniqueConstraint("dc_id", name="uq_dim_distribution_centers_dc_id"),
    )
    op.create_index("ix_dim_distribution_centers_dc_id", "dim_distribution_centers", ["dc_id"], unique=False)

    op.create_table(
        "dim_shipment_statuses",
        sa.Column("status_key", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("status_code", sa.String(), nullable=False),
        sa.Column("status_category", sa.String(), nullable=False),
        sa.Column("is_terminal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("status_key"),
        sa.UniqueConstraint("status_code", name="uq_dim_shipment_statuses_status_code"),
    )

    op.create_table(
        "dim_geographies",
        sa.Column("geo_key", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("country_code", sa.String(), nullable=False),
        sa.Column("region_name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("geo_key"),
        sa.UniqueConstraint("country_code", "region_name", name="uq_dim_geographies_country_region"),
    )

    # 2. ETL Lineage and Quality Audit Tables
    op.create_table(
        "etl_batch_runs",
        sa.Column("batch_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("pipeline_name", sa.String(), server_default="operational_to_olap_sync", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), server_default="RUNNING", nullable=False),
        sa.Column("records_extracted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_loaded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_rejected", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("batch_id"),
    )

    op.create_table(
        "etl_rejected_records",
        sa.Column("rejection_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_table", sa.String(), nullable=False),
        sa.Column("source_record_id", sa.String(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("rejection_id"),
        sa.ForeignKeyConstraint(["batch_id"], ["etl_batch_runs.batch_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_etl_rejected_records_batch_id", "etl_rejected_records", ["batch_id"], unique=False)

    # 3. Fact Tables
    op.create_table(
        "fact_shipments_sla",
        sa.Column("fact_sla_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dispatch_date_key", sa.Integer(), nullable=True),
        sa.Column("deadline_date_key", sa.Integer(), nullable=True),
        sa.Column("delivery_date_key", sa.Integer(), nullable=True),
        sa.Column("brand_key", sa.BigInteger(), nullable=False),
        sa.Column("carrier_key", sa.BigInteger(), nullable=False),
        sa.Column("dc_key", sa.BigInteger(), nullable=False),
        sa.Column("status_key", sa.BigInteger(), nullable=False),
        sa.Column("geo_key", sa.BigInteger(), nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("brand_order_ref", sa.String(), nullable=True),
        sa.Column("sla_status", sa.String(), nullable=False),
        sa.Column("responsible_party", sa.String(), nullable=True),
        sa.Column("freight_amount", sa.Numeric(precision=12, scale=2), server_default="0.00", nullable=False),
        sa.Column("sla_target_days", sa.Integer(), server_default="3", nullable=False),
        sa.Column("actual_business_days", sa.Integer(), nullable=True),
        sa.Column("delay_business_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_sla_breached", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_at_risk", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("business_hours_remaining", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("lead_time_hours", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("etl_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_system", sa.String(), server_default="operational_db", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("fact_sla_id"),
        sa.ForeignKeyConstraint(["brand_key"], ["dim_brands.brand_key"]),
        sa.ForeignKeyConstraint(["carrier_key"], ["dim_carriers.carrier_key"]),
        sa.ForeignKeyConstraint(["dc_key"], ["dim_distribution_centers.dc_key"]),
        sa.ForeignKeyConstraint(["deadline_date_key"], ["dim_dates.date_key"]),
        sa.ForeignKeyConstraint(["delivery_date_key"], ["dim_dates.date_key"]),
        sa.ForeignKeyConstraint(["dispatch_date_key"], ["dim_dates.date_key"]),
        sa.ForeignKeyConstraint(["geo_key"], ["dim_geographies.geo_key"]),
        sa.ForeignKeyConstraint(["status_key"], ["dim_shipment_statuses.status_key"]),
        sa.UniqueConstraint("label_id", name="uq_fact_shipments_sla_label_id"),
    )
    op.create_index("ix_fact_shipments_sla_brand_key", "fact_shipments_sla", ["brand_key"], unique=False)
    op.create_index("ix_fact_shipments_sla_carrier_key", "fact_shipments_sla", ["carrier_key"], unique=False)
    op.create_index("ix_fact_shipments_sla_dispatch_date_key", "fact_shipments_sla", ["dispatch_date_key"], unique=False)
    op.create_index("ix_fact_shipments_sla_deadline_date_key", "fact_shipments_sla", ["deadline_date_key"], unique=False)

    op.create_table(
        "fact_financial_penalties",
        sa.Column("fact_penalty_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("calculation_date_key", sa.Integer(), nullable=False),
        sa.Column("brand_key", sa.BigInteger(), nullable=False),
        sa.Column("carrier_key", sa.BigInteger(), nullable=False),
        sa.Column("status_key", sa.BigInteger(), nullable=False),
        sa.Column("geo_key", sa.BigInteger(), nullable=False),
        sa.Column("penalty_id", sa.BigInteger(), nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("incident_reference", sa.String(), nullable=False),
        sa.Column("responsible_party", sa.String(), nullable=False),
        sa.Column("delay_level", sa.String(), nullable=False),
        sa.Column("calculation_status", sa.String(), nullable=False),
        sa.Column("contract_rule_applied", sa.String(), nullable=False),
        sa.Column("freight_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("delay_business_days", sa.Integer(), nullable=False),
        sa.Column("penalty_percentage", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("base_penalty_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("maximum_penalty_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("penalty_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("is_carrier_payable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_client_owed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("etl_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_system", sa.String(), server_default="operational_db", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("fact_penalty_id"),
        sa.ForeignKeyConstraint(["brand_key"], ["dim_brands.brand_key"]),
        sa.ForeignKeyConstraint(["calculation_date_key"], ["dim_dates.date_key"]),
        sa.ForeignKeyConstraint(["carrier_key"], ["dim_carriers.carrier_key"]),
        sa.ForeignKeyConstraint(["geo_key"], ["dim_geographies.geo_key"]),
        sa.ForeignKeyConstraint(["status_key"], ["dim_shipment_statuses.status_key"]),
        sa.UniqueConstraint("penalty_id", name="uq_fact_financial_penalties_penalty_id"),
    )
    op.create_index("ix_fact_financial_penalties_brand_key", "fact_financial_penalties", ["brand_key"], unique=False)
    op.create_index("ix_fact_financial_penalties_carrier_key", "fact_financial_penalties", ["carrier_key"], unique=False)
    op.create_index("ix_fact_financial_penalties_date_key", "fact_financial_penalties", ["calculation_date_key"], unique=False)

    op.create_table(
        "fact_shipment_events",
        sa.Column("fact_event_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_date_key", sa.Integer(), nullable=False),
        sa.Column("brand_key", sa.BigInteger(), nullable=True),
        sa.Column("carrier_key", sa.BigInteger(), nullable=False),
        sa.Column("status_key", sa.BigInteger(), nullable=False),
        sa.Column("anomaly_id", sa.BigInteger(), nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("raw_status", sa.String(), nullable=False),
        sa.Column("canonical_status", sa.String(), nullable=False),
        sa.Column("anomaly_type", sa.String(), nullable=True),
        sa.Column("etl_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_system", sa.String(), server_default="operational_db", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("fact_event_id"),
        sa.ForeignKeyConstraint(["brand_key"], ["dim_brands.brand_key"]),
        sa.ForeignKeyConstraint(["carrier_key"], ["dim_carriers.carrier_key"]),
        sa.ForeignKeyConstraint(["event_date_key"], ["dim_dates.date_key"]),
        sa.ForeignKeyConstraint(["status_key"], ["dim_shipment_statuses.status_key"]),
        sa.UniqueConstraint("anomaly_id", name="uq_fact_shipment_events_anomaly_id"),
    )
    op.create_index("ix_fact_shipment_events_event_date_key", "fact_shipment_events", ["event_date_key"], unique=False)
    op.create_index("ix_fact_shipment_events_carrier_key", "fact_shipment_events", ["carrier_key"], unique=False)

    op.create_table(
        "fact_carrier_settlements",
        sa.Column("fact_settlement_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_start_date_key", sa.Integer(), nullable=False),
        sa.Column("period_end_date_key", sa.Integer(), nullable=False),
        sa.Column("carrier_key", sa.BigInteger(), nullable=False),
        sa.Column("settlement_id", sa.BigInteger(), nullable=False),
        sa.Column("period_code", sa.String(), nullable=False),
        sa.Column("settlement_status", sa.String(), nullable=False),
        sa.Column("total_penalties_count", sa.Integer(), nullable=False),
        sa.Column("total_freight_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total_owed_to_clients", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total_recoverable_from_carrier", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("net_settlement_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("etl_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_system", sa.String(), server_default="operational_db", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("fact_settlement_id"),
        sa.ForeignKeyConstraint(["carrier_key"], ["dim_carriers.carrier_key"]),
        sa.ForeignKeyConstraint(["period_end_date_key"], ["dim_dates.date_key"]),
        sa.ForeignKeyConstraint(["period_start_date_key"], ["dim_dates.date_key"]),
        sa.UniqueConstraint("settlement_id", name="uq_fact_carrier_settlements_settlement_id"),
    )
    op.create_index("ix_fact_carrier_settlements_carrier_key", "fact_carrier_settlements", ["carrier_key"], unique=False)


def downgrade() -> None:
    op.drop_table("fact_carrier_settlements")
    op.drop_table("fact_shipment_events")
    op.drop_table("fact_financial_penalties")
    op.drop_table("fact_shipments_sla")
    op.drop_table("etl_rejected_records")
    op.drop_table("etl_batch_runs")
    op.drop_table("dim_geographies")
    op.drop_table("dim_shipment_statuses")
    op.drop_table("dim_distribution_centers")
    op.drop_table("dim_carriers")
    op.drop_table("dim_brands")
    op.drop_table("dim_dates")
