"""Add order and shipping-label uniqueness constraints and indexes.

Revision ID: f6b2a9d14c83
Revises: c4a1209b7e6f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6b2a9d14c83"
down_revision: Union[str, None] = "c4a1209b7e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_tracking_number = connection.execute(
        sa.text(
            "SELECT tracking_number, COUNT(*) "
            "FROM shipping_labels GROUP BY tracking_number HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_tracking_number is not None:
        raise RuntimeError(
            "Cannot add uq_shipping_labels_tracking_number: duplicate tracking number "
            f"{duplicate_tracking_number[0]!r} exists. Deduplicate shipping_labels first."
        )

    duplicate_order_reference = connection.execute(
        sa.text(
            "SELECT brand_id, brand_order_ref, COUNT(*) "
            "FROM orders GROUP BY brand_id, brand_order_ref HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_order_reference is not None:
        raise RuntimeError(
            "Cannot add uq_orders_brand_order_ref: duplicate order reference "
            f"{duplicate_order_reference[1]!r} exists for brand {duplicate_order_reference[0]}. "
            "Deduplicate orders first."
        )

    op.create_unique_constraint(
        "uq_shipping_labels_tracking_number",
        "shipping_labels",
        ["tracking_number"],
    )
    op.create_unique_constraint(
        "uq_orders_brand_order_ref",
        "orders",
        ["brand_id", "brand_order_ref"],
    )
    op.create_index("ix_orders_brand_id", "orders", ["brand_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_shipping_labels_order_id", "shipping_labels", ["order_id"])
    op.create_index("ix_shipping_labels_carrier_id", "shipping_labels", ["carrier_id"])


def downgrade() -> None:
    op.drop_index("ix_shipping_labels_carrier_id", table_name="shipping_labels")
    op.drop_index("ix_shipping_labels_order_id", table_name="shipping_labels")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_brand_id", table_name="orders")
    op.drop_constraint(
        "uq_orders_brand_order_ref", "orders", type_="unique"
    )
    op.drop_constraint(
        "uq_shipping_labels_tracking_number", "shipping_labels", type_="unique"
    )
