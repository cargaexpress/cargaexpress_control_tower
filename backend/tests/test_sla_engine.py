from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.dispatch import Dispatch
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import CalendarHoliday
from app.services.sla_engine import SlaEngineService


@pytest.mark.asyncio
async def test_sla_calculation_friday_after_cutoff_with_monday_holiday(db_session: AsyncSession):
    """Validate Worked Example SCN-02 / CA-02:

    Dispatched on Friday at 17:00 (after 16:00 cutoff).
    SLA is 2 business days.
    Monday is a holiday.
    Result: Deadline must be Wednesday at 18:00 local time.
    """
    engine = SlaEngineService()

    # Pre-seed Monday holiday for CO
    monday_holiday = date(2026, 11, 2)
    db_session.add(
        CalendarHoliday(
            country_code="CO",
            holiday_date=monday_holiday,
            name="All Saints Day Holiday",
            year=2026,
            is_national=True,
        )
    )
    await db_session.flush()

    # Friday at 17:00 local Bogota time (UTC-5 -> 22:00 UTC)
    bogota_tz = ZoneInfo("America/Bogota")
    dispatched_local = datetime(2026, 10, 30, 17, 0, 0, tzinfo=bogota_tz)
    dispatched_utc = dispatched_local.astimezone(UTC)

    # Calculate deadline for 2 business days
    sla_start_date, deadline_utc = await engine.calculate_delivery_deadline(
        db=db_session,
        dispatched_at_utc=dispatched_utc,
        sla_business_days=2,
        destination_country="CO",
    )

    # Day 0: Saturday (Oct 31) because Friday was after 16:00
    assert sla_start_date == date(2026, 10, 31)

    # Deadline local time must be Wednesday (Nov 4) at 18:00
    deadline_local = deadline_utc.astimezone(bogota_tz)
    assert deadline_local.date() == date(2026, 11, 4)
    assert deadline_local.hour == 18
    assert deadline_local.minute == 0


@pytest.mark.asyncio
async def test_sla_cross_country_uses_destination_calendar(db_session: AsyncSession):
    """Validate SCN-12: DC in Mexico, destination in Peru.

    Uses the destination calendar (Peru holidays) rather than Mexico (ADR-0010).
    """
    engine = SlaEngineService()

    # July 28 & 29 are Peru National Holidays (Fiestas Patrias), but normal days in Mexico
    db_session.add(
        CalendarHoliday(
            country_code="PE",
            holiday_date=date(2026, 7, 28),
            name="Fiestas Patrias",
            year=2026,
            is_national=True,
        )
    )
    await db_session.flush()

    # Dispatched on Monday July 27 at 10:00 (before 16:00) with STANDARD (3 business days)
    mexico_tz = ZoneInfo("America/Mexico_City")
    dispatched_local = datetime(2026, 7, 27, 10, 0, 0, tzinfo=mexico_tz)
    dispatched_utc = dispatched_local.astimezone(UTC)

    sla_start_date, deadline_utc = await engine.calculate_delivery_deadline(
        db=db_session,
        dispatched_at_utc=dispatched_utc,
        sla_business_days=3,
        destination_country="PE",
        origin_country="MX",
    )

    # Day 0: Monday July 27 (dispatched before 16:00)
    assert sla_start_date == date(2026, 7, 27)

    # 3 business days excluding Tuesday July 28 (holiday) -> Wed 29 (day 1), Thu 30 (day 2), Fri 31 (day 3)
    lima_tz = ZoneInfo("America/Lima")
    deadline_local = deadline_utc.astimezone(lima_tz)
    assert deadline_local.hour == 18
    assert deadline_local.minute == 0
    assert deadline_local.date() >= date(2026, 7, 30)


@pytest.mark.asyncio
async def test_at_risk_detection_when_under_24_hours_and_not_out_for_delivery(
    db_session: AsyncSession,
):
    """Validate RN-04: At-risk classification when <= 24 business hours remain and status != OUT_FOR_DELIVERY."""
    # Seed Order and Label
    brand = Brand(name="TestBrand", tier="TIER_1", is_active=True)
    dc = DistributionCenter(code="DC-TEST", name="Test DC", city="Bogota", country_code="CO")
    carrier = Carrier(name="SimCarrier Alpha", integration_type="webhook", status="active")
    st = ShipmentType(shipment_type_code="STANDARD", description="Standard 3 days")
    db_session.add_all([brand, dc, carrier, st])
    await db_session.flush()

    order = Order(
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code="STANDARD",
        brand_order_ref="REF-RISK-01",
        destination_country="CO",
        freight_value=Decimal("150.00"),
        status="IN_TRANSIT",
    )
    db_session.add(order)
    await db_session.flush()

    dispatch = Dispatch(
        dc_id=dc.dc_id,
        carrier_id=carrier.carrier_id,
        dispatched_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(dispatch)
    await db_session.flush()

    label = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-RISK-001",
        dispatch_id=dispatch.dispatch_id,
        status="IN_TRANSIT",
    )
    db_session.add(label)
    await db_session.flush()

    # Evaluate at a time that is 14 business hours before the deadline
    engine = SlaEngineService()
    _, deadline_utc = await engine.calculate_delivery_deadline(
        db=db_session,
        dispatched_at_utc=dispatch.dispatched_at,
        sla_business_days=3,
        destination_country="CO",
    )

    eval_time = deadline_utc - timedelta(hours=14)
    result = await engine.evaluate_shipment_sla(db_session, label, current_time_utc=eval_time)

    assert result.is_at_risk is True
    assert "remaining before deadline" in result.risk_reason
    assert result.sla_status == "PENDING"

    # Now verify that if status changes to OUT_FOR_DELIVERY, it is NOT at risk (SCN-09)
    label.status = "OUT_FOR_DELIVERY"
    result_out = await engine.evaluate_shipment_sla(db_session, label, current_time_utc=eval_time)
    assert result_out.is_at_risk is False


@pytest.mark.asyncio
async def test_order_sla_endpoint_whole_order_compliance(
    client: AsyncClient, db_session: AsyncSession
):
    """Validate RN-07 / HU-33: Endpoint GET /api/v1/sla/orders/{id}.

    Whole order is compliant only if ALL labels are delivered on time.
    """
    brand = Brand(name="Brand Multi", tier="TIER_1", is_active=True)
    dc = DistributionCenter(code="DC-MULTI", name="Multi DC", city="Bogota", country_code="CO")
    carrier = Carrier(name="SimCarrier Beta", integration_type="webhook", status="active")
    st = ShipmentType(shipment_type_code="EXPRESS", description="Express 1 day")
    db_session.add_all([brand, dc, carrier, st])
    await db_session.flush()

    order = Order(
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code="EXPRESS",
        brand_order_ref="REF-MULTI-01",
        destination_country="CO",
        freight_value=Decimal("200.00"),
        status="IN_TRANSIT",
    )
    db_session.add(order)
    await db_session.flush()

    dispatch = Dispatch(
        dc_id=dc.dc_id,
        carrier_id=carrier.carrier_id,
        dispatched_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(dispatch)
    await db_session.flush()

    label1 = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-M-001",
        dispatch_id=dispatch.dispatch_id,
        status="DELIVERED",
    )
    label2 = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-M-002",
        dispatch_id=dispatch.dispatch_id,
        status="IN_TRANSIT",
    )
    db_session.add_all([label1, label2])
    await db_session.commit()

    # Call endpoint using client's default configured API key header
    response = await client.get(f"/api/v1/sla/orders/{order.order_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == order.order_id
    assert len(data["labels_sla"]) == 2

    assert data["overall_order_compliant"] is True
