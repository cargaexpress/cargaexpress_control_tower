"""Create shipment alerts table (RN-04)

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-03 07:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shipment_alerts",
        sa.Column("alert_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.Column("carrier_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), server_default="WARNING", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("hours_remaining", sa.Float(), nullable=True),
        sa.Column("exception_duration_hours", sa.Float(), nullable=True),
        sa.Column("exception_detail", sa.String(), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("alert_id"),
        sa.ForeignKeyConstraint(["carrier_id"], ["carriers.carrier_id"]),
        sa.ForeignKeyConstraint(["label_id"], ["shipping_labels.label_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_shipment_alerts_alert_type", "shipment_alerts", ["alert_type"], unique=False)
    op.create_index("ix_shipment_alerts_is_resolved", "shipment_alerts", ["is_resolved"], unique=False)
    op.create_index("ix_shipment_alerts_tracking_number", "shipment_alerts", ["tracking_number"], unique=False)
    op.create_index("ix_shipment_alerts_carrier_id", "shipment_alerts", ["carrier_id"], unique=False)
    op.create_index("ix_shipment_alerts_created_at", "shipment_alerts", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_shipment_alerts_created_at", table_name="shipment_alerts")
    op.drop_index("ix_shipment_alerts_carrier_id", table_name="shipment_alerts")
    op.drop_index("ix_shipment_alerts_tracking_number", table_name="shipment_alerts")
    op.drop_index("ix_shipment_alerts_is_resolved", table_name="shipment_alerts")
    op.drop_index("ix_shipment_alerts_alert_type", table_name="shipment_alerts")
    op.drop_table("shipment_alerts")
