from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
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
from app.services.type_b_connector import TypeBConnectorService


async def _seed_test_carrier_b(db_session):
    """Seed test data for Type B carrier tests."""
    brand = Brand(brand_id=1, name="Brand B", tier="standard", is_active=True)
    dc = DistributionCenter(dc_id=1, code="DC01", name="Main DC", city="Bogota", country_code="CO")
    shipment_type = ShipmentType(shipment_type_code="STD", description="Standard Delivery")
    carrier = Carrier(carrier_id=10, name="SimCarrier A", integration_type="api", status="active")

    db_session.add_all([brand, dc, shipment_type, carrier])
    await db_session.commit()

    mappings = [
        StateMapping(
            id=101,
            carrier_id=carrier.carrier_id,
            raw_status="IN_TRANSIT",
            canonical_status="IN_TRANSIT",
        ),
        StateMapping(
            id=102,
            carrier_id=carrier.carrier_id,
            raw_status="DELIVERED",
            canonical_status="DELIVERED",
        ),
    ]
    db_session.add_all(mappings)
    await db_session.commit()
    state_mapping_cache.invalidate()

    order = Order(
        order_id=10,
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=shipment_type.shipment_type_code,
        brand_order_ref="ORD-TYPEB-001",
        destination_country="CO",
        destination_region="Antioquia",
        freight_value=Decimal("15000.00"),
        status="CREATED",
        order_lines=[
            OrderLine(order_line_id=10, order_id=10, line_number=1, sku="SKU-B", quantity_ordered=1)
        ],
        recipient=OrderRecipient(
            order_id=10,
            full_name="Cliente B",
            address_line="Cra 50 # 20-10",
            city="Medellin",
        ),
    )
    db_session.add(order)
    await db_session.commit()

    label = ShippingLabel(
        label_id=10,
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-TYPEB-001",
        status="CREATED",
    )
    label_delivered = ShippingLabel(
        label_id=11,
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-TYPEB-DELIVERED",
        status="DELIVERED",
    )
    db_session.add_all([label, label_delivered])
    await db_session.commit()

    return {
        "carrier": carrier,
        "label": label,
        "label_delivered": label_delivered,
    }


@pytest.mark.asyncio
async def test_type_b_connector_fetches_and_normalizes_events(db_session):
    """Subtask 1 & 2: Client queries Type B API and normalizes status."""
    await _seed_test_carrier_b(db_session)

    mock_events_payload = {
        "carrier": "A",
        "total": 1,
        "limit": 100,
        "offset": 0,
        "events": [
            {
                "event_key": "EVT-B-001",
                "tracking_number": "TRK-TYPEB-001",
                "status": "IN_TRANSIT",
                "event_time": "2026-10-20T10:00:00Z",
            }
        ],
    }

    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=mock_events_payload)
    )
    mock_client = httpx.AsyncClient(transport=mock_transport)

    connector = TypeBConnectorService(client=mock_client)
    summary = await connector.sync_carrier(
        db=db_session,
        carrier_name="SimCarrier A",
        base_url="http://mock-carrier-a:8001",
    )

    assert summary.status == "completed"
    assert summary.total_fetched == 1
    assert summary.normalized == 1
    assert summary.anomalies == 0
    assert summary.errors == 0

    # Verify database update
    updated_label = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-TYPEB-001")
        )
    ).scalar_one()
    assert updated_label.status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_type_b_connector_handles_rate_limit_with_exponential_backoff(db_session):
    """Subtask 3: Handles HTTP 429 Rate Limit with backoff and retry."""
    await _seed_test_carrier_b(db_session)

    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                429,
                json={"carrier": "A", "error": "Rate limit exceeded"},
                headers={"Retry-After": "1"},
            )
        return httpx.Response(
            200,
            json={
                "carrier": "A",
                "total": 1,
                "limit": 100,
                "offset": 0,
                "events": [
                    {
                        "event_key": "EVT-B-002",
                        "tracking_number": "TRK-TYPEB-001",
                        "status": "IN_TRANSIT",
                    }
                ],
            },
        )

    sleep_mock = AsyncMock()
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    connector = TypeBConnectorService(
        max_retries=2,
        base_delay_seconds=0.1,
        client=mock_client,
        sleep_fn=sleep_mock,
    )
    summary = await connector.sync_carrier(
        db=db_session,
        carrier_name="SimCarrier A",
        base_url="http://mock-carrier-a:8001",
    )

    assert summary.status == "completed"
    assert summary.rate_limits_encountered == 1
    assert summary.total_fetched == 1
    assert call_count == 2
    assert sleep_mock.await_count == 1


@pytest.mark.asyncio
async def test_type_b_connector_exhausts_retries_on_persistent_rate_limit(db_session):
    """Subtask 3: Persistent 429 returns failed status after exhausting retries."""
    await _seed_test_carrier_b(db_session)

    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": "Rate limit exceeded"})
    )
    sleep_mock = AsyncMock()
    mock_client = httpx.AsyncClient(transport=mock_transport)

    connector = TypeBConnectorService(
        max_retries=2,
        base_delay_seconds=0.01,
        client=mock_client,
        sleep_fn=sleep_mock,
    )
    summary = await connector.sync_carrier(
        db=db_session,
        carrier_name="SimCarrier A",
        base_url="http://mock-carrier-a:8001",
    )

    assert summary.status == "failed"
    assert summary.rate_limits_encountered == 3
    assert "Rate limit exceeded" in str(summary.error_message)


@pytest.mark.asyncio
async def test_type_b_connector_enforces_rn02_anomaly_on_terminal_status(db_session):
    """Subtask 2 & 3: Reusing normalization ensures RN-02 is preserved during sync."""
    await _seed_test_carrier_b(db_session)

    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "carrier": "A",
                "total": 1,
                "limit": 100,
                "offset": 0,
                "events": [
                    {
                        "event_key": "EVT-B-003",
                        "tracking_number": "TRK-TYPEB-DELIVERED",
                        "status": "IN_TRANSIT",
                    }
                ],
            },
        )
    )
    mock_client = httpx.AsyncClient(transport=mock_transport)

    connector = TypeBConnectorService(client=mock_client)
    summary = await connector.sync_carrier(
        db=db_session,
        carrier_name="SimCarrier A",
        base_url="http://mock-carrier-a:8001",
    )

    assert summary.status == "completed"
    assert summary.anomalies == 1
    assert summary.normalized == 0

    # Verify label remains DELIVERED (RN-02)
    label = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-TYPEB-DELIVERED")
        )
    ).scalar_one()
    assert label.status == "DELIVERED"

    # Verify anomaly recorded
    anomaly = (
        await db_session.execute(
            select(TrackingAnomaly).where(TrackingAnomaly.tracking_number == "TRK-TYPEB-DELIVERED")
        )
    ).scalar_one_or_none()
    assert anomaly is not None
    assert anomaly.anomaly_type == "TERMINAL_STATE_REVERSION"


@pytest.mark.asyncio
async def test_type_b_sync_api_endpoint(client, db_session, monkeypatch):
    """Test manual trigger endpoint POST /api/v1/sync/type-b."""
    await _seed_test_carrier_b(db_session)

    async def mock_sync_all(*args, **kwargs):
        from app.services.type_b_connector import CarrierSyncSummary

        return [
            CarrierSyncSummary(
                carrier="SimCarrier A", total_fetched=5, normalized=5, status="completed"
            )
        ]

    monkeypatch.setattr(TypeBConnectorService, "sync_all_carriers", mock_sync_all)

    response = await client.post("/api/v1/sync/type-b")
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "completed"
    assert len(res["results"]) == 1
    assert res["results"][0]["carrier"] == "SimCarrier A"
    assert res["results"][0]["normalized"] == 5
