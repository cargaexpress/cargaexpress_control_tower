from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import ShipmentAlert
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.dispatch import Dispatch
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.services.risk_monitoring_service import RiskMonitoringService
from app.services.sla_engine import SlaEngineService


async def _seed_test_shipment(
    db: AsyncSession,
    tracking_number: str,
    status: str,
    dispatched_at: datetime,
    shipment_type: str = "STANDARD",
) -> tuple[Order, ShippingLabel, Carrier]:
    brand = Brand(name="AlertBrand", tier="TIER_1", is_active=True)
    dc = DistributionCenter(code="DC-ALERT", name="Alert DC", city="Bogota", country_code="CO")
    carrier = Carrier(name="SimCarrier Alpha", integration_type="webhook", status="active")
    st = ShipmentType(shipment_type_code=shipment_type, description=f"{shipment_type} shipping")
    db.add_all([brand, dc, carrier, st])
    await db.flush()

    order = Order(
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=shipment_type,
        brand_order_ref=f"REF-{tracking_number}",
        destination_country="CO",
        freight_value=Decimal("120.00"),
        status=status,
    )
    db.add(order)
    await db.flush()

    dispatch = Dispatch(
        dc_id=dc.dc_id,
        carrier_id=carrier.carrier_id,
        dispatched_at=dispatched_at,
    )
    db.add(dispatch)
    await db.flush()

    label = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number=tracking_number,
        dispatch_id=dispatch.dispatch_id,
        status=status,
    )
    db.add(label)
    await db.flush()
    return order, label, carrier


@pytest.mark.asyncio
async def test_preventive_24h_alert_generation(db_session: AsyncSession):
    """Rule 1: Generate preventive alert when <= 24 business hours remain and NOT OUT_FOR_DELIVERY."""
    service = RiskMonitoringService()
    sla_engine = SlaEngineService()

    # Dispatch 2 days ago
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, carrier = await _seed_test_shipment(
        db=db_session,
        tracking_number="TRK-ALERT-24H",
        status="IN_TRANSIT",
        dispatched_at=dispatch_time,
        shipment_type="STANDARD",
    )

    # Verify deadline
    _, deadline = await sla_engine.calculate_delivery_deadline(db_session, dispatch_time, 3, "CO")
    # Scan at 14h before deadline
    scan_time = deadline - timedelta(hours=14)

    summary = await service.scan_and_generate_alerts(db_session, current_time_utc=scan_time)
    assert summary.alerts_generated >= 1
    assert summary.preventive_24h_alerts >= 1

    # Check alert persisted in database
    stmt = select(ShipmentAlert).where(
        ShipmentAlert.tracking_number == "TRK-ALERT-24H",
        ShipmentAlert.alert_type == "PREVENTIVE_24H",
    )
    res = await db_session.execute(stmt)
    alert = res.scalar_one_or_none()
    assert alert is not None
    assert alert.carrier_id == carrier.carrier_id
    assert alert.is_resolved is False
    assert alert.hours_remaining is not None
    assert alert.hours_remaining <= 24.0


@pytest.mark.asyncio
async def test_preventive_24h_alert_skipped_if_out_for_delivery(db_session: AsyncSession):
    """Rule 1 condition: Do NOT generate preventive alert if already OUT_FOR_DELIVERY."""
    service = RiskMonitoringService()
    sla_engine = SlaEngineService()

    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, _ = await _seed_test_shipment(
        db=db_session,
        tracking_number="TRK-NO-ALERT-DELIV",
        status="OUT_FOR_DELIVERY",
        dispatched_at=dispatch_time,
        shipment_type="STANDARD",
    )

    _, deadline = await sla_engine.calculate_delivery_deadline(db_session, dispatch_time, 3, "CO")
    scan_time = deadline - timedelta(hours=10)

    summary = await service.scan_and_generate_alerts(db_session, current_time_utc=scan_time)
    # Should not generate 24h alert because status is OUT_FOR_DELIVERY
    assert summary.preventive_24h_alerts == 0


@pytest.mark.asyncio
async def test_prolonged_exception_alert_generation(db_session: AsyncSession):
    """Rule 2: Generate alert when shipment is in EXCEPTION for > 12 hours."""
    service = RiskMonitoringService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, carrier = await _seed_test_shipment(
        db=db_session,
        tracking_number="TRK-ALERT-EXC",
        status="EXCEPTION",
        dispatched_at=dispatch_time,
        shipment_type="STANDARD",
    )

    now = dispatch_time + timedelta(hours=16)
    summary = await service.scan_and_generate_alerts(db_session, current_time_utc=now)

    assert summary.prolonged_exception_alerts >= 1

    stmt = select(ShipmentAlert).where(
        ShipmentAlert.tracking_number == "TRK-ALERT-EXC",
        ShipmentAlert.alert_type == "PROLONGED_EXCEPTION",
    )
    res = await db_session.execute(stmt)
    alert = res.scalar_one_or_none()
    assert alert is not None
    assert alert.carrier_id == carrier.carrier_id
    assert alert.severity == "CRITICAL"
    assert alert.exception_duration_hours is not None
    assert alert.exception_duration_hours > 12.0


@pytest.mark.asyncio
async def test_auto_resolution_when_shipment_progresses(db_session: AsyncSession):
    """Verify alerts auto-resolve when the shipment progresses to OUT_FOR_DELIVERY or resolves EXCEPTION."""
    service = RiskMonitoringService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, _ = await _seed_test_shipment(
        db=db_session,
        tracking_number="TRK-AUTO-RESOLVE",
        status="IN_TRANSIT",
        dispatched_at=dispatch_time,
        shipment_type="STANDARD",
    )

    sla_engine = SlaEngineService()
    _, deadline = await sla_engine.calculate_delivery_deadline(db_session, dispatch_time, 3, "CO")
    # Scan at 12h before deadline
    scan_time = deadline - timedelta(hours=12)
    await service.scan_and_generate_alerts(db_session, current_time_utc=scan_time)

    # Verify alert exists active
    stmt = select(ShipmentAlert).where(ShipmentAlert.tracking_number == "TRK-AUTO-RESOLVE")
    res = await db_session.execute(stmt)
    alert = res.scalar_one_or_none()
    assert alert is not None
    assert alert.is_resolved is False

    # Simulate transition to OUT_FOR_DELIVERY
    label.status = "OUT_FOR_DELIVERY"
    await db_session.flush()

    # Re-scan: alert must be automatically resolved
    summary = await service.scan_and_generate_alerts(
        db_session, current_time_utc=scan_time + timedelta(hours=2)
    )
    assert summary.alerts_resolved >= 1

    await db_session.refresh(alert)
    assert alert.is_resolved is True
    assert alert.resolved_at is not None
    assert "OUT_FOR_DELIVERY" in alert.resolution_notes


@pytest.mark.asyncio
async def test_alerts_api_list_and_resolve(client: AsyncClient, db_session: AsyncSession):
    """Test REST endpoints GET /api/v1/alerts and POST /api/v1/alerts/{id}/resolve."""
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)
    _, label, carrier = await _seed_test_shipment(
        db=db_session,
        tracking_number="TRK-API-ALERT",
        status="EXCEPTION",
        dispatched_at=dispatch_time,
    )

    # Seed alert directly
    alert = ShipmentAlert(
        label_id=label.label_id,
        carrier_id=carrier.carrier_id,
        tracking_number=label.tracking_number,
        alert_type="PROLONGED_EXCEPTION",
        severity="CRITICAL",
        message="Test alert",
        is_resolved=False,
    )
    db_session.add(alert)
    await db_session.commit()

    # 1. Query GET /api/v1/alerts
    resp = await client.get("/api/v1/alerts?is_resolved=false")
    assert resp.status_code == 200
    alerts_data = resp.json()
    assert len(alerts_data) >= 1
    found = next((a for a in alerts_data if a["tracking_number"] == "TRK-API-ALERT"), None)
    assert found is not None
    assert found["alert_type"] == "PROLONGED_EXCEPTION"

    # 2. Resolve alert manually via POST /api/v1/alerts/{id}/resolve
    resolve_resp = await client.post(
        f"/api/v1/alerts/{alert.alert_id}/resolve",
        json={"resolution_notes": "Carrier contacted and delivery rescheduled."},
    )
    assert resolve_resp.status_code == 200
    res_data = resolve_resp.json()
    assert res_data["is_resolved"] is True
    assert "Carrier contacted" in res_data["resolution_notes"]
