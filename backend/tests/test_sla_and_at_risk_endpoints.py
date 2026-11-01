"""Integration tests for SLA calculation and at-risk order endpoints (HU-33).

Exercises GET /api/v1/orders/{id}/sla and GET /api/v1/orders/at-risk
against the real calculations from HU-31 and HU-32.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.dispatch import Dispatch
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.order_line import OrderLine
from app.models.order_recipient import OrderRecipient
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.tracking_event import TrackingEvent
from app.services.holiday_service import holiday_service


@pytest.fixture(autouse=True)
def preload_colombia_holidays():
    """Ensure holiday cache includes Monday Oct 26, 2026 for Colombia."""
    holiday_service.preload_holidays("CO", 2026, ["2026-10-26"])
    yield
    holiday_service.clear_cache()


async def _seed_test_brand_and_dc(db_session, brand_id: int = 1, brand_name: str = "Test Brand"):
    brand = await db_session.get(Brand, brand_id)
    if not brand:
        brand = Brand(brand_id=brand_id, name=brand_name, tier="standard", is_active=True)
        db_session.add(brand)

    dc = (
        await db_session.execute(
            select(DistributionCenter).where(DistributionCenter.code == "DC-BOG")
        )
    ).scalar_one_or_none()
    if not dc:
        dc = DistributionCenter(code="DC-BOG", name="Bogota DC", city="Bogota", country_code="CO")
        db_session.add(dc)

    st = (
        await db_session.execute(
            select(ShipmentType).where(ShipmentType.shipment_type_code == "STD")
        )
    ).scalar_one_or_none()
    if not st:
        st = ShipmentType(shipment_type_code="STD", description="Standard Shipment")
        db_session.add(st)

    carrier = (
        await db_session.execute(select(Carrier).where(Carrier.name == "Carrier Alpha"))
    ).scalar_one_or_none()
    if not carrier:
        carrier = Carrier(name="Carrier Alpha", integration_type="WEBHOOK", status="ACTIVE")
        db_session.add(carrier)

    await db_session.commit()
    await db_session.refresh(brand)
    await db_session.refresh(dc)
    await db_session.refresh(st)
    await db_session.refresh(carrier)
    return brand, dc, st, carrier


async def _seed_full_order(
    db_session,
    brand_id: int = 1,
    status: str = "IN_TRANSIT",
    ref: str = "ORD-001",
    is_at_risk: bool = False,
    at_risk_reason: str | None = None,
    dispatched_at: datetime | None = None,
) -> tuple[Order, ShippingLabel]:
    brand, dc, st, carrier = await _seed_test_brand_and_dc(db_session, brand_id=brand_id)

    order = Order(
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=st.shipment_type_code,
        brand_order_ref=ref,
        destination_country="CO",
        destination_region="Cundinamarca",
        freight_value=Decimal("25000.00"),
        status=status,
        is_at_risk=is_at_risk,
        at_risk_reason=at_risk_reason,
        at_risk_evaluated_at=datetime.now(UTC) if is_at_risk else None,
    )
    order.order_lines.append(
        OrderLine(line_number=1, sku="SKU-TEST-1", description="Item 1", quantity_ordered=1)
    )
    order.recipient = OrderRecipient(
        full_name="Destinatario Test",
        email="test@example.com",
        phone="3001234567",
        address_line="Calle 100 # 15-20",
        city="Bogota",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    # Attach dispatch and shipping label if dispatched
    disp_dt = dispatched_at or datetime(2026, 10, 23, 10, 0, 0, tzinfo=UTC)
    dispatch = Dispatch(
        dc_id=dc.dc_id,
        carrier_id=carrier.carrier_id,
        dispatched_at=disp_dt,
    )
    db_session.add(dispatch)
    await db_session.commit()
    await db_session.refresh(dispatch)

    label = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number=f"TRK-{ref}",
        dispatch_id=dispatch.dispatch_id,
        status=status,
    )
    db_session.add(label)
    await db_session.commit()
    await db_session.refresh(label)

    return order, label


# =====================================================================
# Tests: GET /api/v1/orders/{order_id}/sla
# =====================================================================


@pytest.mark.asyncio
async def test_get_order_sla_matches_project_test_case(client, db_session):
    """Friday 5:00 PM dispatch (22:00 UTC) + Monday holiday = deadline Wednesday Oct 28 (RN-03).

    Matches the project's exact test case specified in HU-31/HU-33.
    """
    # Friday 5:00 PM local Bogota (22:00 UTC) -> after 16:00 cutoff
    dispatch_dt = datetime(2026, 10, 23, 22, 0, 0, tzinfo=UTC)
    order, _ = await _seed_full_order(
        db_session,
        brand_id=1,
        status="IN_TRANSIT",
        ref="ORD-SLA-01",
        is_at_risk=False,
        dispatched_at=dispatch_dt,
    )

    response = await client.get(f"/api/v1/orders/{order.order_id}/sla")

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order.order_id
    assert body["brand_id"] == 1
    assert body["status"] == "IN_TRANSIT"
    assert body["destination_country"] == "CO"
    assert body["sla_business_days"] == 2
    assert body["deadline_date"] == "2026-10-28"
    assert body["compliance_status"] == "PENDING"
    assert body["is_compliant"] is None
    assert body["is_after_cutoff"] is True


@pytest.mark.asyncio
async def test_get_order_sla_on_track_not_at_risk(client, db_session):
    """Order with > 24 business hours remaining before deadline is not at risk."""
    now_utc = datetime.now(UTC)
    order, _ = await _seed_full_order(
        db_session,
        brand_id=1,
        status="IN_TRANSIT",
        ref="ORD-SLA-NOT-AT-RISK",
        is_at_risk=False,
        dispatched_at=now_utc,
    )

    response = await client.get(
        f"/api/v1/orders/{order.order_id}/sla", params={"sla_business_days": 5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_at_risk"] is False
    assert body["compliance_status"] == "PENDING"
    assert body["business_hours_remaining"] is not None
    assert body["business_hours_remaining"] > 24.0


@pytest.mark.asyncio
async def test_get_order_sla_at_risk_flagged(client, db_session):
    """Order with is_at_risk=True exposes at-risk reasons and business hours remaining."""
    order, _ = await _seed_full_order(
        db_session,
        brand_id=1,
        status="IN_TRANSIT",
        ref="ORD-SLA-AT-RISK",
        is_at_risk=True,
        at_risk_reason="FEWER_THAN_24_BUSINESS_HOURS_REMAINING: 14.0h left",
    )

    response = await client.get(f"/api/v1/orders/{order.order_id}/sla")

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order.order_id
    assert body["is_at_risk"] is True
    assert "FEWER_THAN_24_BUSINESS_HOURS_REMAINING" in (body["at_risk_reason"] or "")
    assert body["compliance_status"] in {"PENDING", "MISSED"}


@pytest.mark.asyncio
async def test_get_order_sla_delivered_compliant_met(client, db_session):
    """Order delivered on or before SLA deadline -> compliance_status MET, is_compliant True."""
    # Dispatched on Oct 23, deadline Oct 28
    dispatch_dt = datetime(2026, 10, 23, 10, 0, 0, tzinfo=UTC)
    order, label = await _seed_full_order(
        db_session,
        brand_id=1,
        status="DELIVERED",
        ref="ORD-SLA-DELIV-ONTIME",
        is_at_risk=False,
        dispatched_at=dispatch_dt,
    )

    # Seed DELIVERED tracking event on Oct 27 (before deadline Oct 28)
    evt = TrackingEvent(
        carrier_id=label.carrier_id,
        label_id=label.label_id,
        tracking_number=label.tracking_number,
        raw_status="DELIVERED_OK",
        canonical_status="DELIVERED",
        event_timestamp=datetime(2026, 10, 27, 14, 0, 0, tzinfo=UTC),
    )
    db_session.add(evt)
    await db_session.commit()

    response = await client.get(f"/api/v1/orders/{order.order_id}/sla")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DELIVERED"
    assert body["compliance_status"] == "MET"
    assert body["is_compliant"] is True
    assert body["is_at_risk"] is False


@pytest.mark.asyncio
async def test_get_order_sla_delivered_breached_missed(client, db_session):
    """Order delivered after SLA deadline -> compliance_status MISSED, is_compliant False."""
    dispatch_dt = datetime(2026, 10, 23, 10, 0, 0, tzinfo=UTC)
    order, label = await _seed_full_order(
        db_session,
        brand_id=1,
        status="DELIVERED",
        ref="ORD-SLA-DELIV-LATE",
        is_at_risk=False,
        dispatched_at=dispatch_dt,
    )

    # Seed DELIVERED event on Oct 30 (deadline was Oct 28 23:59:59)
    evt = TrackingEvent(
        carrier_id=label.carrier_id,
        label_id=label.label_id,
        tracking_number=label.tracking_number,
        raw_status="DELIVERED_LATE",
        canonical_status="DELIVERED",
        event_timestamp=datetime(2026, 10, 30, 9, 0, 0, tzinfo=UTC),
    )
    db_session.add(evt)
    await db_session.commit()

    response = await client.get(f"/api/v1/orders/{order.order_id}/sla")

    assert response.status_code == 200
    body = response.json()
    assert body["compliance_status"] == "MISSED"
    assert body["is_compliant"] is False


@pytest.mark.asyncio
async def test_get_order_sla_not_found_returns_404(client):
    """Querying non-existent order SLA returns 404."""
    response = await client.get("/api/v1/orders/999999/sla")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_order_sla_cross_brand_tenant_isolation(client, db_session, monkeypatch):
    """Brand 2 cannot query SLA for an order owned by Brand 1 (CA-10 / RN-10)."""
    order, _ = await _seed_full_order(db_session, brand_id=1, ref="ORD-BRAND-1")

    # Authenticate as Brand 2
    api_key_b2 = "brand-2-api-key"
    monkeypatch.setattr(settings, "brand_api_keys", {api_key_b2: 2})

    response = await client.get(
        f"/api/v1/orders/{order.order_id}/sla",
        headers={"X-API-Key": api_key_b2},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_order_sla_coordinator_access_cross_brand(client, db_session, monkeypatch):
    """Coordinator with X-Admin-Token can query SLA for any order across brands."""
    order, _ = await _seed_full_order(db_session, brand_id=2, ref="ORD-BRAND-2")

    monkeypatch.setattr(settings, "admin_api_key", "coordinator-admin-secret")

    response = await client.get(
        f"/api/v1/orders/{order.order_id}/sla",
        headers={"X-Admin-Token": "coordinator-admin-secret"},
    )

    assert response.status_code == 200
    assert response.json()["order_id"] == order.order_id


@pytest.mark.asyncio
async def test_get_order_sla_unprefixed_alias_route(client, db_session):
    """GET /orders/{id}/sla works identically to /api/v1/orders/{id}/sla."""
    order, _ = await _seed_full_order(db_session, brand_id=1, ref="ORD-ALIAS-01")

    response = await client.get(f"/orders/{order.order_id}/sla")

    assert response.status_code == 200
    assert response.json()["order_id"] == order.order_id


# =====================================================================
# Tests: GET /api/v1/orders/at-risk
# =====================================================================


@pytest.mark.asyncio
async def test_list_at_risk_orders_empty(client, db_session):
    """When no orders are at risk, returns empty list."""
    await _seed_full_order(db_session, brand_id=1, status="IN_TRANSIT", is_at_risk=False)

    response = await client.get("/api/v1/orders/at-risk")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_at_risk_orders_returns_only_flagged_active_orders(client, db_session):
    """Lists orders where is_at_risk is True and status is non-terminal."""
    order_at_risk, _ = await _seed_full_order(
        db_session,
        brand_id=1,
        status="IN_TRANSIT",
        ref="ORD-RISK-ACTIVE",
        is_at_risk=True,
        at_risk_reason="FEWER_THAN_24_BUSINESS_HOURS_REMAINING",
    )
    # Order not at risk
    await _seed_full_order(
        db_session,
        brand_id=1,
        status="IN_TRANSIT",
        ref="ORD-SAFE",
        is_at_risk=False,
    )
    # Terminal order (should be excluded even if marked is_at_risk)
    await _seed_full_order(
        db_session,
        brand_id=1,
        status="DELIVERED",
        ref="ORD-DELIV-EXCLUDED",
        is_at_risk=True,
    )

    response = await client.get("/api/v1/orders/at-risk")

    assert response.status_code == 200
    orders = response.json()
    assert isinstance(orders, list)
    assert len(orders) == 1
    assert orders[0]["order_id"] == order_at_risk.order_id
    assert orders[0]["is_at_risk"] is True
    assert "FEWER_THAN_24_BUSINESS_HOURS_REMAINING" in orders[0]["at_risk_reason"]


@pytest.mark.asyncio
async def test_list_at_risk_orders_pagination(client, db_session):
    """Supports skip and limit pagination parameters."""
    for i in range(1, 4):
        await _seed_full_order(
            db_session,
            brand_id=1,
            status="IN_TRANSIT",
            ref=f"ORD-PAG-{i}",
            is_at_risk=True,
            at_risk_reason=f"Reason {i}",
        )

    response = await client.get("/api/v1/orders/at-risk", params={"skip": 1, "limit": 1})

    assert response.status_code == 200
    orders = response.json()
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_list_at_risk_orders_tenant_isolation(client, db_session, monkeypatch):
    """Brand 1 only sees Brand 1 at-risk orders. Brand 2 only sees Brand 2."""
    order_b1, _ = await _seed_full_order(
        db_session,
        brand_id=1,
        ref="ORD-B1-RISK",
        is_at_risk=True,
        at_risk_reason="B1 Risk",
    )
    order_b2, _ = await _seed_full_order(
        db_session,
        brand_id=2,
        ref="ORD-B2-RISK",
        is_at_risk=True,
        at_risk_reason="B2 Risk",
    )

    # Request as Brand 1
    resp_b1 = await client.get("/api/v1/orders/at-risk")
    assert resp_b1.status_code == 200
    ids_b1 = [o["order_id"] for o in resp_b1.json()]
    assert order_b1.order_id in ids_b1
    assert order_b2.order_id not in ids_b1

    # Request as Brand 2
    api_key_b2 = "brand-2-secret"
    monkeypatch.setattr(settings, "brand_api_keys", {client.headers["X-API-Key"]: 1, api_key_b2: 2})
    resp_b2 = await client.get("/api/v1/orders/at-risk", headers={"X-API-Key": api_key_b2})
    assert resp_b2.status_code == 200
    ids_b2 = [o["order_id"] for o in resp_b2.json()]
    assert order_b2.order_id in ids_b2
    assert order_b1.order_id not in ids_b2


@pytest.mark.asyncio
async def test_list_at_risk_orders_coordinator_sees_all_and_can_filter(
    client, db_session, monkeypatch
):
    """Coordinator with X-Admin-Token sees orders across all brands and can filter by brand_id."""
    order_b1, _ = await _seed_full_order(
        db_session,
        brand_id=1,
        ref="ORD-COORD-B1",
        is_at_risk=True,
        at_risk_reason="Risk 1",
    )
    order_b2, _ = await _seed_full_order(
        db_session,
        brand_id=2,
        ref="ORD-COORD-B2",
        is_at_risk=True,
        at_risk_reason="Risk 2",
    )

    monkeypatch.setattr(settings, "admin_api_key", "coord-token")
    headers = {"X-Admin-Token": "coord-token"}

    # Coordinator sees all
    all_resp = await client.get("/api/v1/orders/at-risk", headers=headers)
    assert all_resp.status_code == 200
    all_ids = [o["order_id"] for o in all_resp.json()]
    assert order_b1.order_id in all_ids
    assert order_b2.order_id in all_ids

    # Coordinator filters by brand_id=2
    filter_resp = await client.get(
        "/api/v1/orders/at-risk", headers=headers, params={"brand_id": 2}
    )
    assert filter_resp.status_code == 200
    filtered_ids = [o["order_id"] for o in filter_resp.json()]
    assert order_b2.order_id in filtered_ids
    assert order_b1.order_id not in filtered_ids


@pytest.mark.asyncio
async def test_brand_requesting_other_brand_at_risk_returns_403(client, db_session):
    """A brand passing ?brand_id=<different_brand> gets 403 Forbidden."""
    await _seed_full_order(db_session, brand_id=1, is_at_risk=True)

    response = await client.get("/api/v1/orders/at-risk", params={"brand_id": 999})

    assert response.status_code == 403
    assert "forbidden" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_at_risk_orders_unprefixed_alias_route(client, db_session):
    """GET /orders/at-risk works identically to /api/v1/orders/at-risk."""
    order, _ = await _seed_full_order(
        db_session,
        brand_id=1,
        ref="ORD-ALIAS-RISK",
        is_at_risk=True,
        at_risk_reason="Alias test",
    )

    response = await client.get("/orders/at-risk")

    assert response.status_code == 200
    assert any(o["order_id"] == order.order_id for o in response.json())


# =====================================================================
# Tests: Authentication & Security
# =====================================================================


@pytest.mark.asyncio
async def test_endpoints_reject_missing_authentication(monkeypatch):
    """Requests with no auth header are rejected with 401 when API key is configured."""
    monkeypatch.setattr(settings, "api_key", "active-system-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauth_client:
        sla_resp = await unauth_client.get("/api/v1/orders/1/sla")
        risk_resp = await unauth_client.get("/api/v1/orders/at-risk")

        assert sla_resp.status_code == 401
        assert risk_resp.status_code == 401


@pytest.mark.asyncio
async def test_endpoints_reject_invalid_token(monkeypatch):
    """Requests with invalid API key are rejected with 401 when API key is configured."""
    monkeypatch.setattr(settings, "api_key", "active-system-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "invalid-secret"},
    ) as bad_client:
        sla_resp = await bad_client.get("/api/v1/orders/1/sla")
        risk_resp = await bad_client.get("/api/v1/orders/at-risk")

        assert sla_resp.status_code == 401
        assert risk_resp.status_code == 401


@pytest.mark.asyncio
async def test_endpoints_return_503_when_no_key_configured(monkeypatch):
    """Endpoints return 503 Service Unavailable when no auth keys are configured."""
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "admin_api_key", "")
    monkeypatch.setattr(settings, "brand_api_keys", {})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client_no_keys:
        sla_resp = await client_no_keys.get("/api/v1/orders/1/sla")
        risk_resp = await client_no_keys.get("/api/v1/orders/at-risk")

        assert sla_resp.status_code == 503
        assert risk_resp.status_code == 503
