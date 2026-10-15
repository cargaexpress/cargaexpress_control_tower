"""Seed state_mapping for simulated carriers.

Creates (if they do not exist) three simulated carriers and their initial
status translation to the canonical vocabulary. Each speaks a different
format on purpose: Alpha uses English words, Beta uses numeric codes,
and Gamma uses Spanish.

Safe to run multiple times: does not duplicate carriers or mappings and
does NOT overwrite changes made subsequently from the admin endpoint.

Revision ID: b7e24d51c8a9
Revises: a3f1c9d27b45
Create Date: 2026-10-08 12:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e24d51c8a9'
down_revision: Union[str, None] = 'a3f1c9d27b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIMULATED_INTEGRATION_TYPE = "simulated"

# {carrier_name: {reported_status: canonical_status}}
SEED: dict[str, dict[str, str]] = {
    "SimCarrier Alpha": {
        "CREATED": "CREATED",
        "PICKED_UP": "PICKED_UP",
        "IN_TRANSIT": "IN_TRANSIT",
        "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
        "DELIVERED": "DELIVERED",
        "DELIVERY_ATTEMPT_FAILED": "DELIVERY_FAILED",
        "RETURNED_TO_SENDER": "RETURNED",
        "CANCELLED": "CANCELLED",
        "HELD_AT_CUSTOMS": "EXCEPTION",
    },
    "SimCarrier Beta": {
        "100": "CREATED",
        "200": "PICKED_UP",
        "300": "IN_TRANSIT",
        "400": "OUT_FOR_DELIVERY",
        "500": "DELIVERED",
        "600": "DELIVERY_FAILED",
        "700": "RETURNED",
        "800": "CANCELLED",
        "900": "EXCEPTION",
    },
    "SimCarrier Gamma": {
        "Generada": "CREATED",
        "Recolectada": "PICKED_UP",
        "En tránsito": "IN_TRANSIT",
        "En reparto": "OUT_FOR_DELIVERY",
        "Entregada": "DELIVERED",
        "Intento fallido": "DELIVERY_FAILED",
        "Devuelta al remitente": "RETURNED",
        "Cancelada": "CANCELLED",
        "Novedad": "EXCEPTION",
    },
}


def upgrade() -> None:
    conn = op.get_bind()

    for carrier_name, mappings in SEED.items():
        carrier_id = conn.execute(
            sa.text("SELECT carrier_id FROM carriers WHERE name = :name"),
            {"name": carrier_name},
        ).scalar()

        if carrier_id is None:
            carrier_id = conn.execute(
                sa.text(
                    "INSERT INTO carriers (name, integration_type, status) "
                    "VALUES (:name, :integration_type, 'active') RETURNING carrier_id"
                ),
                {"name": carrier_name, "integration_type": SIMULATED_INTEGRATION_TYPE},
            ).scalar_one()

        for source_status, canonical_status in mappings.items():
            conn.execute(
                sa.text(
                    "INSERT INTO state_mapping (carrier_id, source_status, canonical_status) "
                    "VALUES (:carrier_id, :source_status, :canonical_status) "
                    "ON CONFLICT (carrier_id, source_status) DO NOTHING"
                ),
                {
                    "carrier_id": carrier_id,
                    "source_status": source_status,
                    "canonical_status": canonical_status,
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    names = list(SEED)

    # Remove all mappings for simulated carriers (including edited ones).
    conn.execute(
        sa.text(
            "DELETE FROM state_mapping WHERE carrier_id IN "
            "(SELECT carrier_id FROM carriers WHERE name = ANY(:names))"
        ),
        {"names": names},
    )
    # Remove carriers only if they remain simulated and are not referenced.
    conn.execute(
        sa.text(
            "DELETE FROM carriers c WHERE c.name = ANY(:names) "
            "AND c.integration_type = :integration_type "
            "AND NOT EXISTS (SELECT 1 FROM shipping_labels s WHERE s.carrier_id = c.carrier_id) "
            "AND NOT EXISTS (SELECT 1 FROM dispatches d WHERE d.carrier_id = c.carrier_id)"
        ),
        {"names": names, "integration_type": SIMULATED_INTEGRATION_TYPE},
    )
