"""Align state mappings with the HU-12 canonical catalog.

Revision ID: c4a1209b7e6f
Revises: b7e24d51c8a9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4a1209b7e6f"
down_revision: Union[str, None] = "b7e24d51c8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CANONICAL_STATUSES = (
    "CREATED",
    "PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "EXCEPTION",
    "DELIVERED",
    "RETURNED",
    "LOST_OR_DAMAGED",
)

SEED: dict[str, dict[str, str]] = {
    "SimCarrier Alpha": {
        "CREATED": "CREATED",
        "PICKED_UP": "PICKED_UP",
        "IN_TRANSIT": "IN_TRANSIT",
        "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
        "DELIVERED": "DELIVERED",
        "DELIVERY_ATTEMPT_FAILED": "EXCEPTION",
        "RETURNED_TO_SENDER": "RETURNED",
        "CANCELLED": "EXCEPTION",
        "HELD_AT_CUSTOMS": "EXCEPTION",
        "LOST_OR_DAMAGED": "LOST_OR_DAMAGED",
    },
    "SimCarrier Beta": {
        "100": "CREATED",
        "200": "PICKED_UP",
        "300": "IN_TRANSIT",
        "400": "OUT_FOR_DELIVERY",
        "500": "DELIVERED",
        "600": "EXCEPTION",
        "700": "RETURNED",
        "800": "EXCEPTION",
        "900": "EXCEPTION",
        "999": "LOST_OR_DAMAGED",
    },
    "SimCarrier Gamma": {
        "Generada": "CREATED",
        "Recolectada": "PICKED_UP",
        "En tránsito": "IN_TRANSIT",
        "En reparto": "OUT_FOR_DELIVERY",
        "Entregada": "DELIVERED",
        "Intento fallido": "EXCEPTION",
        "Devuelta al remitente": "RETURNED",
        "Cancelada": "EXCEPTION",
        "Novedad": "EXCEPTION",
        "Perdida o dañada": "LOST_OR_DAMAGED",
    },
}


def upgrade() -> None:
    # Rename legacy fields in place so existing mapping IDs and data survive.
    # Renombra columnas existentes para conservar IDs y datos guardados.
    op.drop_constraint(
        "uq_state_mapping_carrier_source", "state_mapping", type_="unique"
    )
    op.alter_column(
        "state_mapping", "mapping_id", new_column_name="id"
    )
    op.alter_column(
        "state_mapping", "source_status", new_column_name="raw_status"
    )
    op.create_unique_constraint(
        "uq_state_mapping_carrier_raw_status",
        "state_mapping",
        ["carrier_id", "raw_status"],
    )

    canonical_values = ", ".join(f"'{value}'" for value in CANONICAL_STATUSES)
    # Old unsupported values become EXCEPTION before the DB constraint is added.
    # Los valores antiguos no válidos pasan a EXCEPTION antes de crear el CHECK.
    op.execute(
        sa.text(
            "UPDATE state_mapping SET canonical_status = 'EXCEPTION' "
            f"WHERE canonical_status NOT IN ({canonical_values})"
        )
    )
    op.create_check_constraint(
        "ck_state_mapping_canonical_status",
        "state_mapping",
        f"canonical_status IN ({canonical_values})",
    )

    connection = op.get_bind()
    # Add missing defaults without overwriting business edits already in the table.
    # Inserta valores faltantes sin sobrescribir ajustes comerciales existentes.
    for carrier_name, mappings in SEED.items():
        for raw_status, canonical_status in mappings.items():
            connection.execute(
                sa.text(
                    "INSERT INTO state_mapping (carrier_id, raw_status, canonical_status) "
                    "SELECT carrier_id, :raw_status, :canonical_status "
                    "FROM carriers WHERE name = :carrier_name "
                    "ON CONFLICT (carrier_id, raw_status) DO NOTHING"
                ),
                {
                    "carrier_name": carrier_name,
                    "raw_status": raw_status,
                    "canonical_status": canonical_status,
                },
            )


def downgrade() -> None:
    op.drop_constraint(
        "ck_state_mapping_canonical_status", "state_mapping", type_="check"
    )
    op.drop_constraint(
        "uq_state_mapping_carrier_raw_status", "state_mapping", type_="unique"
    )
    op.alter_column(
        "state_mapping", "raw_status", new_column_name="source_status"
    )
    op.alter_column(
        "state_mapping", "id", new_column_name="mapping_id"
    )
    op.create_unique_constraint(
        "uq_state_mapping_carrier_source",
        "state_mapping",
        ["carrier_id", "source_status"],
    )
