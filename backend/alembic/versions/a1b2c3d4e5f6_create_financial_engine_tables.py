"""Create financial engine tables: attributions, penalties, settlements, and ledger (FR-04, FR-05, BR-05, BR-06, BR-08)

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-11-03 08:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Financial Settlements
    op.create_table(
        "financial_settlements",
        sa.Column("settlement_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("carrier_id", sa.BigInteger(), nullable=False),
        sa.Column("period_code", sa.String(), nullable=False),
        sa.Column("period_start_date", sa.Date(), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=False),
        sa.Column("total_penalties_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_freight_amount", sa.Numeric(precision=14, scale=2), server_default="0.00", nullable=False),
        sa.Column("total_owed_to_clients", sa.Numeric(precision=14, scale=2), server_default="0.00", nullable=False),
        sa.Column("total_recoverable_from_carrier", sa.Numeric(precision=14, scale=2), server_default="0.00", nullable=False),
        sa.Column("net_settlement_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("status", sa.String(), server_default="PENDING_VALIDATION", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("settlement_id"),
        sa.ForeignKeyConstraint(["carrier_id"], ["carriers.carrier_id"]),
        sa.UniqueConstraint("carrier_id", "period_code", name="uq_financial_settlements_carrier_period"),
    )
    op.create_index("ix_financial_settlements_carrier_id", "financial_settlements", ["carrier_id"], unique=False)
    op.create_index("ix_financial_settlements_period_code", "financial_settlements", ["period_code"], unique=False)
    op.create_index("ix_financial_settlements_status", "financial_settlements", ["status"], unique=False)

    # 2. Shipment Attributions
    op.create_table(
        "shipment_attributions",
        sa.Column("attribution_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("carrier_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("responsible_party", sa.String(), nullable=False),
        sa.Column("incident_type", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_details", sa.Text(), nullable=True),
        sa.Column("order_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("attribution_id"),
        sa.ForeignKeyConstraint(["carrier_id"], ["carriers.carrier_id"]),
        sa.ForeignKeyConstraint(["label_id"], ["shipping_labels.label_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"]),
        sa.UniqueConstraint("label_id", name="uq_shipment_attributions_label_id"),
    )
    op.create_index("ix_shipment_attributions_responsible_party", "shipment_attributions", ["responsible_party"], unique=False)
    op.create_index("ix_shipment_attributions_carrier_id", "shipment_attributions", ["carrier_id"], unique=False)
    op.create_index("ix_shipment_attributions_tracking_number", "shipment_attributions", ["tracking_number"], unique=False)

    # 3. Freight Penalties
    op.create_table(
        "freight_penalties",
        sa.Column("penalty_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("carrier_id", sa.BigInteger(), nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=False),
        sa.Column("settlement_id", sa.BigInteger(), nullable=True),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("incident_reference", sa.String(), nullable=False),
        sa.Column("responsible_party", sa.String(), nullable=False),
        sa.Column("freight_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("delay_business_days", sa.Integer(), nullable=False),
        sa.Column("delay_level", sa.String(), server_default="NO_DELAY", nullable=False),
        sa.Column("calculation_status", sa.String(), server_default="PENDING_APPROVAL", nullable=False),
        sa.Column("penalty_percentage", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("base_penalty_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("maximum_penalty_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("penalty_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("is_carrier_payable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_client_owed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("contract_rule_applied", sa.String(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("penalty_id"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.brand_id"]),
        sa.ForeignKeyConstraint(["carrier_id"], ["carriers.carrier_id"]),
        sa.ForeignKeyConstraint(["label_id"], ["shipping_labels.label_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.order_id"]),
        sa.ForeignKeyConstraint(["settlement_id"], ["financial_settlements.settlement_id"]),
        sa.UniqueConstraint("label_id", "incident_reference", name="uq_freight_penalties_label_incident"),
    )
    op.create_index("ix_freight_penalties_carrier_id", "freight_penalties", ["carrier_id"], unique=False)
    op.create_index("ix_freight_penalties_brand_id", "freight_penalties", ["brand_id"], unique=False)
    op.create_index("ix_freight_penalties_settlement_id", "freight_penalties", ["settlement_id"], unique=False)
    op.create_index("ix_freight_penalties_responsible_party", "freight_penalties", ["responsible_party"], unique=False)

    # 4. Financial Ledger Entries
    op.create_table(
        "financial_ledger_entries",
        sa.Column("entry_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("settlement_id", sa.BigInteger(), nullable=False),
        sa.Column("carrier_id", sa.BigInteger(), nullable=False),
        sa.Column("brand_id", sa.BigInteger(), nullable=True),
        sa.Column("penalty_id", sa.BigInteger(), nullable=True),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), server_default="COP", nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.brand_id"]),
        sa.ForeignKeyConstraint(["carrier_id"], ["carriers.carrier_id"]),
        sa.ForeignKeyConstraint(["penalty_id"], ["freight_penalties.penalty_id"]),
        sa.ForeignKeyConstraint(["settlement_id"], ["financial_settlements.settlement_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_financial_ledger_entries_settlement_id", "financial_ledger_entries", ["settlement_id"], unique=False)
    op.create_index("ix_financial_ledger_entries_carrier_id", "financial_ledger_entries", ["carrier_id"], unique=False)
    op.create_index("ix_financial_ledger_entries_entry_type", "financial_ledger_entries", ["entry_type"], unique=False)

    # 5. Universal Penalty Configurations (Universal Progressive Penalty Scale)
    op.create_table(
        "universal_penalty_configs",
        sa.Column("config_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(), server_default="v1.0", nullable=False),
        sa.Column("delay_level", sa.String(), nullable=False),  # NO_DELAY, LOW, MODERATE, HIGH, CRITICAL
        sa.Column("min_delay_days", sa.Integer(), nullable=True),
        sa.Column("max_delay_days", sa.Integer(), nullable=True),
        sa.Column("penalty_percentage", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("maximum_cap_percentage", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("approval_status", sa.String(), server_default="PENDING_APPROVAL", nullable=False),  # PENDING_APPROVAL, APPROVED, REJECTED
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("config_id"),
        sa.UniqueConstraint("version", "delay_level", name="uq_universal_penalty_configs_version_level"),
    )
    op.create_index("ix_universal_penalty_configs_version", "universal_penalty_configs", ["version"], unique=False)
    op.create_index("ix_universal_penalty_configs_is_active", "universal_penalty_configs", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_table("universal_penalty_configs")
    op.drop_table("financial_ledger_entries")
    op.drop_table("freight_penalties")
    op.drop_table("shipment_attributions")
    op.drop_table("financial_settlements")
