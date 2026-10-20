from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.order_line import OrderLine
from app.models.order_recipient import OrderRecipient
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.state_mapping import StateMapping
from app.models.tracking_anomaly import TrackingAnomaly
from app.services.state_mapping_cache import state_mapping_cache


async def _seed_test_infrastructure(db_session):
    """Seed test brands, carriers, mappings, orders, and shipping labels."""
    brand = Brand(brand_id=1, name="Test Brand", tier="standard", is_active=True)
    dc = DistributionCenter(dc_id=1, code="DC01", name="Main DC", city="Bogota", country_code="CO")
    shipment_type = ShipmentType(shipment_type_code="STD", description="Standard Delivery")

    # 5 Type A Carriers
    carrier_alpha = Carrier(
        carrier_id=1, name="SimCarrier Alpha", integration_type="webhook", status="active"
    )
    carrier_beta = Carrier(
        carrier_id=2, name="SimCarrier Beta", integration_type="webhook", status="active"
    )
    carrier_gamma = Carrier(
        carrier_id=3, name="SimCarrier Gamma", integration_type="webhook", status="active"
    )
    carrier_delta = Carrier(
        carrier_id=4, name="SimCarrier Delta", integration_type="webhook", status="active"
    )
    carrier_epsilon = Carrier(
        carrier_id=5, name="SimCarrier Epsilon", integration_type="webhook", status="active"
    )

    db_session.add_all(
        [
            brand,
            dc,
            shipment_type,
            carrier_alpha,
            carrier_beta,
            carrier_gamma,
            carrier_delta,
            carrier_epsilon,
        ]
    )
    await db_session.commit()

    # Mappings
    mappings = [
        # Alpha
        StateMapping(
            id=1,
            carrier_id=carrier_alpha.carrier_id,
            raw_status="IN_TRANSIT",
            canonical_status="IN_TRANSIT",
        ),
        StateMapping(
            id=2,
            carrier_id=carrier_alpha.carrier_id,
            raw_status="DELIVERED",
            canonical_status="DELIVERED",
        ),
        StateMapping(
            id=3,
            carrier_id=carrier_alpha.carrier_id,
            raw_status="OUT_FOR_DELIVERY",
            canonical_status="OUT_FOR_DELIVERY",
        ),
        # Beta
        StateMapping(
            id=4,
            carrier_id=carrier_beta.carrier_id,
            raw_status="300",
            canonical_status="IN_TRANSIT",
        ),
        StateMapping(
            id=5, carrier_id=carrier_beta.carrier_id, raw_status="500", canonical_status="DELIVERED"
        ),
        # Gamma
        StateMapping(
            id=6,
            carrier_id=carrier_gamma.carrier_id,
            raw_status="En reparto",
            canonical_status="OUT_FOR_DELIVERY",
        ),
        StateMapping(
            id=7,
            carrier_id=carrier_gamma.carrier_id,
            raw_status="Entregada",
            canonical_status="DELIVERED",
        ),
        # Delta
        StateMapping(
            id=8,
            carrier_id=carrier_delta.carrier_id,
            raw_status="HUB",
            canonical_status="IN_TRANSIT",
        ),
        StateMapping(
            id=9,
            carrier_id=carrier_delta.carrier_id,
            raw_status="DEL",
            canonical_status="DELIVERED",
        ),
        # Epsilon
        StateMapping(
            id=10,
            carrier_id=carrier_epsilon.carrier_id,
            raw_status="In transit",
            canonical_status="IN_TRANSIT",
        ),
        StateMapping(
            id=11,
            carrier_id=carrier_epsilon.carrier_id,
            raw_status="Delivered",
            canonical_status="DELIVERED",
        ),
    ]
    db_session.add_all(mappings)
    await db_session.commit()
    state_mapping_cache.invalidate()

    # Test Order
    order = Order(
        order_id=1,
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=shipment_type.shipment_type_code,
        brand_order_ref="ORD-TEST-001",
        destination_country="CO",
        destination_region="Cundinamarca",
        freight_value=Decimal("20000.00"),
        status="CREATED",
        order_lines=[
            OrderLine(order_line_id=1, order_id=1, line_number=1, sku="SKU-1", quantity_ordered=1)
        ],
        recipient=OrderRecipient(
            order_id=1,
            full_name="Destinatario Test",
            address_line="Calle 100 # 15-20",
            city="Bogota",
        ),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    # Shipping Label for Alpha
    label_alpha = ShippingLabel(
        label_id=1,
        order_id=order.order_id,
        carrier_id=carrier_alpha.carrier_id,
        tracking_number="TRK-ALPHA-001",
        status="CREATED",
    )
    # Shipping Label for Beta
    label_beta = ShippingLabel(
        label_id=2,
        order_id=order.order_id,
        carrier_id=carrier_beta.carrier_id,
        tracking_number="TRK-BETA-001",
        status="CREATED",
    )
    # Shipping Label for Gamma
    label_gamma = ShippingLabel(
        label_id=3,
        order_id=order.order_id,
        carrier_id=carrier_gamma.carrier_id,
        tracking_number="TRK-GAMMA-001",
        status="CREATED",
    )
    # Shipping Label already DELIVERED for RN-02 tests
    label_delivered = ShippingLabel(
        label_id=4,
        order_id=order.order_id,
        carrier_id=carrier_alpha.carrier_id,
        tracking_number="TRK-DELIVERED-001",
        status="DELIVERED",
    )

    db_session.add_all([label_alpha, label_beta, label_gamma, label_delivered])
    await db_session.commit()

    return {
        "order": order,
        "carrier_alpha": carrier_alpha,
        "carrier_beta": carrier_beta,
        "carrier_gamma": carrier_gamma,
        "carrier_delta": carrier_delta,
        "carrier_epsilon": carrier_epsilon,
        "label_alpha": label_alpha,
        "label_beta": label_beta,
        "label_gamma": label_gamma,
        "label_delivered": label_delivered,
    }


@pytest.mark.asyncio
async def test_webhook_alpha_flat_json_normalizes_to_canonical_status(client, db_session):
    """Subtask 2 & 4: Raw Alpha flat JSON -> Canonical status on shipping label."""
    await _seed_test_infrastructure(db_session)
    payload = {
        "event_id": "EVT-101",
        "tracking_number": "TRK-ALPHA-001",
        "status": "IN_TRANSIT",
        "occurred_at": "2026-10-20T10:00:00Z",
        "location": "Centro Logistico Bogota",
    }

    response = await client.post(
        "/api/v1/webhooks/alpha",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    res_body = response.json()
    assert res_body["status"] == "processed"
    assert res_body["canonical_status"] == "IN_TRANSIT"
    assert res_body["current_status"] == "IN_TRANSIT"
    assert res_body["is_anomaly"] is False

    # Verify persisted in database
    refreshed = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-ALPHA-001")
        )
    ).scalar_one()
    assert refreshed.status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_webhook_beta_nested_json_normalizes_to_canonical_status(client, db_session):
    """Subtask 2 & 4: Raw Beta nested JSON with numeric code 300 -> Canonical IN_TRANSIT."""
    await _seed_test_infrastructure(db_session)
    payload = {
        "eventId": "EVT-BETA-202",
        "shipment": {"trackingId": "TRK-BETA-001"},
        "event": {"code": "300", "occurredAtEpochMs": 1792496180000},
        "hub": "Hub Medellin",
    }

    response = await client.post(
        "/api/v1/webhooks/beta",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    res_body = response.json()
    assert res_body["canonical_status"] == "IN_TRANSIT"
    assert res_body["current_status"] == "IN_TRANSIT"

    refreshed = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-BETA-001")
        )
    ).scalar_one()
    assert refreshed.status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_webhook_gamma_spanish_json_normalizes_to_canonical_status(client, db_session):
    """Subtask 2 & 4: Raw Gamma Spanish JSON ('En reparto') -> Canonical OUT_FOR_DELIVERY."""
    await _seed_test_infrastructure(db_session)
    payload = {
        "id_evento": "EVT-GAMMA-303",
        "guia": "TRK-GAMMA-001",
        "estado": "En reparto",
        "fecha": "2026-10-20T08:30:00-05:00",
        "ciudad": "Cali",
    }

    response = await client.post(
        "/api/v1/webhooks/gamma",
        json=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 200
    res_body = response.json()
    assert res_body["canonical_status"] == "OUT_FOR_DELIVERY"
    assert res_body["current_status"] == "OUT_FOR_DELIVERY"

    refreshed = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-GAMMA-001")
        )
    ).scalar_one()
    assert refreshed.status == "OUT_FOR_DELIVERY"


@pytest.mark.asyncio
async def test_webhook_rn02_delivered_status_cannot_be_reverted_and_records_anomaly(
    client, db_session
):
    """Subtask 3: RN-02 & CA-01.

    When an event 'IN_TRANSIT' arrives for an already 'DELIVERED' label:
    1. The label's status MUST NOT change (remains DELIVERED).
    2. An anomaly record is saved in tracking_anomalies table.
    3. The response acknowledges the anomaly without crashing.
    """
    await _seed_test_infrastructure(db_session)
    payload = {
        "event_id": "EVT-CHAOS-001",
        "tracking_number": "TRK-DELIVERED-001",
        "status": "IN_TRANSIT",
        "occurred_at": "2026-10-20T12:00:00Z",
    }

    response = await client.post("/api/v1/webhooks/alpha", json=payload)

    assert response.status_code == 200
    res_body = response.json()
    assert res_body["is_anomaly"] is True
    assert res_body["current_status"] == "DELIVERED"
    assert "RN-02" in res_body["anomaly_reason"]

    # 1. Verify label status is still DELIVERED
    refreshed_label = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-DELIVERED-001")
        )
    ).scalar_one()
    assert refreshed_label.status == "DELIVERED"

    # 2. Verify anomaly is persisted in tracking_anomalies table
    anomaly = (
        await db_session.execute(
            select(TrackingAnomaly).where(TrackingAnomaly.tracking_number == "TRK-DELIVERED-001")
        )
    ).scalar_one_or_none()
    assert anomaly is not None
    assert anomaly.anomaly_type == "TERMINAL_STATE_REVERSION"
    assert anomaly.current_status == "DELIVERED"
    assert anomaly.attempted_status == "IN_TRANSIT"
    assert anomaly.raw_status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_webhook_non_existent_tracking_number_records_anomaly(client, db_session):
    """Quality defect 5.3: Unknown tracking numbers record anomaly."""
    await _seed_test_infrastructure(db_session)
    payload = {
        "event_id": "EVT-UNKNOWN-999",
        "tracking_number": "TRK-GHOST-999",
        "status": "IN_TRANSIT",
    }

    response = await client.post("/api/v1/webhooks/alpha", json=payload)

    assert response.status_code == 200
    res_body = response.json()
    assert res_body["is_anomaly"] is True
    assert res_body["anomaly_reason"] == "UNKNOWN_TRACKING_NUMBER"

    anomaly = (
        await db_session.execute(
            select(TrackingAnomaly).where(TrackingAnomaly.tracking_number == "TRK-GHOST-999")
        )
    ).scalar_one_or_none()
    assert anomaly is not None
    assert anomaly.anomaly_type == "UNKNOWN_TRACKING_NUMBER"


@pytest.mark.asyncio
async def test_webhook_unknown_carrier_returns_404(client, db_session):
    """Returns 404 when carrier slug does not exist."""
    payload = {"event_id": "1", "tracking_number": "123", "status": "IN_TRANSIT"}
    response = await client.post("/api/v1/webhooks/carrier_inexistente", json=payload)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_webhook_empty_payload_returns_422(client, db_session):
    """Returns 422 when body is empty."""
    response = await client.post(
        "/api/v1/webhooks/alpha",
        content=b"",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
