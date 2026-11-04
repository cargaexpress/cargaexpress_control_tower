"""Seed all 12 carriers across Type A, Type B, and Type C, and their canonical state mappings.

Revision ID: bdb88a412f83
Revises: h8e4c2f6b315
Create Date: 2026-11-03 06:51:35.205348

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bdb88a412f83'
down_revision: str | None = 'h8e4c2f6b315'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CARRIER_SEED_DATA: list[dict[str, str | dict[str, str]]] = [
    # --- Type A Carriers (Webhooks) ---
    {
        "name": "SimCarrier Alpha",
        "integration_type": "webhook",
        "mappings": {
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
    },
    {
        "name": "SimCarrier Beta",
        "integration_type": "webhook",
        "mappings": {
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
    },
    {
        "name": "SimCarrier Gamma",
        "integration_type": "webhook",
        "mappings": {
            "Generada": "CREATED",
            "Recolectada": "PICKED_UP",
            "En tránsito": "IN_TRANSIT",
            "En tránsit": "IN_TRANSIT",
            "En reparto": "OUT_FOR_DELIVERY",
            "Entregada": "DELIVERED",
            "Intento fallido": "EXCEPTION",
            "Devuelta al remitente": "RETURNED",
            "Cancelada": "EXCEPTION",
            "Novedad": "EXCEPTION",
            "Perdida o dañada": "LOST_OR_DAMAGED",
        },
    },
    {
        "name": "SimCarrier Delta",
        "integration_type": "webhook",
        "mappings": {
            "CREATED": "CREATED",
            "PICK": "PICKED_UP",
            "HUB": "IN_TRANSIT",
            "OUT": "OUT_FOR_DELIVERY",
            "DEL": "DELIVERED",
            "FAIL": "EXCEPTION",
            "RET": "RETURNED",
            "DAM": "LOST_OR_DAMAGED",
        },
    },
    {
        "name": "SimCarrier Epsilon",
        "integration_type": "webhook",
        "mappings": {
            "Created": "CREATED",
            "created": "CREATED",
            "Picked up": "PICKED_UP",
            "In transit": "IN_TRANSIT",
            "Out for delivery": "OUT_FOR_DELIVERY",
            "Delivered": "DELIVERED",
            "Failed attempt": "EXCEPTION",
            "Returned": "RETURNED",
            "Damaged": "LOST_OR_DAMAGED",
        },
    },
    # --- Type B Carriers (REST Polling) ---
    {
        "name": "SimCarrier A",
        "integration_type": "api",
        "mappings": {
            "REGISTERED": "CREATED",
            "COLLECTED": "PICKED_UP",
            "IN_ROUTE": "IN_TRANSIT",
            "AT_HUB": "IN_TRANSIT",
            "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
            "DELIVERED": "DELIVERED",
            "RETURNED": "RETURNED",
            "INCIDENCE": "EXCEPTION",
        },
    },
    {
        "name": "SimCarrier B",
        "integration_type": "api",
        "mappings": {
            "CREATED": "CREATED",
            "PICKED_UP": "PICKED_UP",
            "MOVING": "IN_TRANSIT",
            "ARRIVED": "OUT_FOR_DELIVERY",
            "COMPLETED": "DELIVERED",
            "REJECTED": "EXCEPTION",
            "RETURNED": "RETURNED",
        },
    },
    {
        "name": "SimCarrier C",
        "integration_type": "api",
        "mappings": {
            "NEW": "CREATED",
            "ACCEPTED": "PICKED_UP",
            "TRANSIT": "IN_TRANSIT",
            "LOCAL_DEPOT": "OUT_FOR_DELIVERY",
            "DONE": "DELIVERED",
            "INCIDENT": "EXCEPTION",
            "RETURNED": "RETURNED",
        },
    },
    {
        "name": "SimCarrier D",
        "integration_type": "api",
        "mappings": {
            "OPEN": "CREATED",
            "RECEIVED": "PICKED_UP",
            "ON_ROUTE": "IN_TRANSIT",
            "BRANCH": "OUT_FOR_DELIVERY",
            "FINISHED": "DELIVERED",
            "RETURN": "RETURNED",
            "EXCEPTION": "EXCEPTION",
        },
    },
    # --- Type C Carriers (Batch File Ingestion) ---
    {
        "name": "TransExpress Logistics",
        "integration_type": "file",
        "mappings": {
            "DOC_REC": "CREATED",
            "DISPATCHED": "PICKED_UP",
            "IN_DEPOT": "IN_TRANSIT",
            "OUT_DELIVERY": "OUT_FOR_DELIVERY",
            "INCIDENCE": "EXCEPTION",
            "DELIVERED": "DELIVERED",
            "RETURN_SENDER": "RETURNED",
            "DAMAGED_CARGO": "LOST_OR_DAMAGED",
        },
    },
    {
        "name": "Rapido Andino",
        "integration_type": "file",
        "mappings": {
            "REGISTRADO": "CREATED",
            "RECOLECTADO": "PICKED_UP",
            "TRASLADO_INTERNO": "IN_TRANSIT",
            "RUTA_ENTREGA": "OUT_FOR_DELIVERY",
            "NOVEDAD_DIRECCION": "EXCEPTION",
            "ENTREGADO_OK": "DELIVERED",
            "DEVUELTO_ORIGEN": "RETURNED",
            "EXTRAVIO": "LOST_OR_DAMAGED",
        },
    },
    {
        "name": "Logistica 360",
        "integration_type": "file",
        "mappings": {
            "10": "CREATED",
            "20": "PICKED_UP",
            "30": "IN_TRANSIT",
            "40": "OUT_FOR_DELIVERY",
            "50": "EXCEPTION",
            "90": "DELIVERED",
            "91": "RETURNED",
            "99": "LOST_OR_DAMAGED",
        },
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    for item in CARRIER_SEED_DATA:
        carrier_name = str(item["name"])
        integration_type = str(item["integration_type"])
        mappings = dict(item["mappings"])

        # Check or insert carrier
        carrier_id = conn.execute(
            sa.text("SELECT carrier_id FROM carriers WHERE name = :name"),
            {"name": carrier_name},
        ).scalar()

        if carrier_id is None:
            conn.execute(
                sa.text(
                    "INSERT INTO carriers (name, integration_type, status) "
                    "VALUES (:name, :integration_type, 'active')"
                ),
                {"name": carrier_name, "integration_type": integration_type},
            )
            carrier_id = conn.execute(
                sa.text("SELECT carrier_id FROM carriers WHERE name = :name"),
                {"name": carrier_name},
            ).scalar()

        # Insert missing mappings
        for raw_status, canonical_status in mappings.items():
            existing = conn.execute(
                sa.text(
                    "SELECT 1 FROM state_mapping WHERE carrier_id = :carrier_id AND raw_status = :raw_status"
                ),
                {"carrier_id": carrier_id, "raw_status": raw_status},
            ).scalar()

            if not existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO state_mapping (carrier_id, raw_status, canonical_status) "
                        "VALUES (:carrier_id, :raw_status, :canonical_status)"
                    ),
                    {
                        "carrier_id": carrier_id,
                        "raw_status": raw_status,
                        "canonical_status": canonical_status,
                    },
                )


def downgrade() -> None:
    conn = op.get_bind()
    carrier_names = [
        "SimCarrier Delta",
        "SimCarrier Epsilon",
        "SimCarrier A",
        "SimCarrier B",
        "SimCarrier C",
        "SimCarrier D",
        "TransExpress Logistics",
        "Rapido Andino",
        "Logistica 360",
    ]
    for name in carrier_names:
        carrier_id = conn.execute(
            sa.text("SELECT carrier_id FROM carriers WHERE name = :name"),
            {"name": name},
        ).scalar()
        if carrier_id:
            conn.execute(
                sa.text("DELETE FROM state_mapping WHERE carrier_id = :carrier_id"),
                {"carrier_id": carrier_id},
            )
            conn.execute(
                sa.text("DELETE FROM carriers WHERE carrier_id = :carrier_id"),
                {"carrier_id": carrier_id},
            )
