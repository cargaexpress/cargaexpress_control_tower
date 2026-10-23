"""Create tracking_anomalies table for RN-02 terminal state violations and tracking errors.

Revision ID: g7d3b1e5a204
Revises: f6b2a9d14c83
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g7d3b1e5a204"
down_revision: str | None = "f6b2a9d14c83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tracking_anomalies",
        sa.Column("anomaly_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("carrier_id", sa.BigInteger(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=True),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("attempted_status", sa.String(), nullable=False),
        sa.Column("raw_status", sa.String(), nullable=False),
        sa.Column("anomaly_type", sa.String(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["carrier_id"], ["carriers.carrier_id"]),
        sa.ForeignKeyConstraint(["label_id"], ["shipping_labels.label_id"]),
        sa.PrimaryKeyConstraint("anomaly_id"),
    )
    op.create_index(
        "ix_tracking_anomalies_tracking_number",
        "tracking_anomalies",
        ["tracking_number"],
    )
    op.create_index(
        "ix_tracking_anomalies_carrier_id",
        "tracking_anomalies",
        ["carrier_id"],
    )
    op.create_index(
        "ix_tracking_anomalies_created_at",
        "tracking_anomalies",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tracking_anomalies_created_at", table_name="tracking_anomalies")
    op.drop_index("ix_tracking_anomalies_carrier_id", table_name="tracking_anomalies")
    op.drop_index("ix_tracking_anomalies_tracking_number", table_name="tracking_anomalies")
    op.drop_table("tracking_anomalies")
