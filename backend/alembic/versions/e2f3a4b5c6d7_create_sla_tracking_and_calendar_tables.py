"""Create SLA tracking and calendar holidays tables (RN-03, RN-04)

Revision ID: e2f3a4b5c6d7
Revises: bdb88a412f83
Create Date: 2026-11-03 07:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "bdb88a412f83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Calendar holidays table for country public holidays
    op.create_table(
        "calendar_holidays",
        sa.Column("holiday_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("country_code", sa.CHAR(length=2), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("is_national", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("holiday_id"),
        sa.UniqueConstraint("country_code", "holiday_date", name="uq_calendar_holidays_country_date"),
    )
    op.create_index(
        "ix_calendar_holidays_country_year",
        "calendar_holidays",
        ["country_code", "year"],
        unique=False,
    )

    # 2. Shipment SLA tracking table
    op.create_table(
        "shipment_sla_tracking",
        sa.Column("tracking_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("destination_country", sa.CHAR(length=2), nullable=False),
        sa.Column("shipment_type_code", sa.String(), nullable=False),
        sa.Column("sla_business_days", sa.Integer(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_start_date", sa.Date(), nullable=True),
        sa.Column("deadline_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_at_risk", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("risk_reason", sa.String(), nullable=True),
        sa.Column("business_hours_remaining", sa.Float(), nullable=True),
        sa.Column("exception_open_duration_hours", sa.Float(), nullable=True),
        sa.Column("sla_status", sa.String(), server_default="PENDING", nullable=False),
        sa.Column("responsible_party", sa.String(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("tracking_id"),
        sa.ForeignKeyConstraint(["label_id"], ["shipping_labels.label_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("label_id", name="uq_shipment_sla_tracking_label_id"),
    )
    op.create_index("ix_shipment_sla_tracking_tracking_number", "shipment_sla_tracking", ["tracking_number"], unique=False)
    op.create_index("ix_shipment_sla_tracking_is_at_risk", "shipment_sla_tracking", ["is_at_risk"], unique=False)
    op.create_index("ix_shipment_sla_tracking_sla_status", "shipment_sla_tracking", ["sla_status"], unique=False)
    op.create_index("ix_shipment_sla_tracking_deadline_utc", "shipment_sla_tracking", ["deadline_utc"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_shipment_sla_tracking_deadline_utc", table_name="shipment_sla_tracking")
    op.drop_index("ix_shipment_sla_tracking_sla_status", table_name="shipment_sla_tracking")
    op.drop_index("ix_shipment_sla_tracking_is_at_risk", table_name="shipment_sla_tracking")
    op.drop_index("ix_shipment_sla_tracking_tracking_number", table_name="shipment_sla_tracking")
    op.drop_table("shipment_sla_tracking")

    op.drop_index("ix_calendar_holidays_country_year", table_name="calendar_holidays")
    op.drop_table("calendar_holidays")
