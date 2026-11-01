from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.dispatch import Dispatch
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.state_mapping import StateMapping
from app.models.tracking_event import TrackingEvent
from app.services.at_risk_service import AtRiskService
from app.services.holiday_service import HolidayService
from app.services.normalization_service import normalize_event
from app.services.sla_service import SLAService
from app.services.state_mapping_cache import state_mapping_cache


@pytest.fixture
def mock_holiday_service() -> HolidayService:
    service = HolidayService()
    service.clear_cache()
    # Monday 2026-10-26 is a holiday in CO
    service.preload_holidays("CO", 2026, ["2026-10-26"])
    return service


@pytest.fixture
def at_risk_service_instance(mock_holiday_service: HolidayService) -> AtRiskService:
    sla_svc = SLAService(holidays=mock_holiday_service)
    return AtRiskService(sla_svc=sla_svc, holiday_svc=mock_holiday_service)


async def _seed_test_order(
    db_session,
    status: str = "IN_TRANSIT",
    dispatch_dt: datetime | None = None,
    order_ref: str = "TEST-ORDER-001",
) -> tuple[Order, ShippingLabel, Carrier]:
    """Helper to seed a complete order with DC, carrier, and shipping label."""
    brand = (
        await db_session.execute(select(Brand).where(Brand.name == "Risk Brand"))
    ).scalar_one_or_none()
    if not brand:
        brand = Brand(name="Risk Brand", tier="standard", is_active=True)
        db_session.add(brand)

    dc = (
        await db_session.execute(
            select(DistributionCenter).where(DistributionCenter.code == "DC-BOG")
        )
    ).scalar_one_or_none()
    if not dc:
        dc = DistributionCenter(code="DC-BOG", name="Bogota DC", city="Bogota", country_code="CO")
        db_session.add(dc)

    carrier = (
        await db_session.execute(select(Carrier).where(Carrier.name == "SimCarrier Alpha"))
    ).scalar_one_or_none()
    if not carrier:
        carrier = Carrier(name="SimCarrier Alpha", integration_type="WEBHOOK", status="ACTIVE")
        db_session.add(carrier)

    st = (
        await db_session.execute(
            select(ShipmentType).where(ShipmentType.shipment_type_code == "STD_RISK")
        )
    ).scalar_one_or_none()
    if not st:
        st = ShipmentType(shipment_type_code="STD_RISK", description="Standard Shipment")
        db_session.add(st)

    await db_session.commit()
    await db_session.refresh(brand)
    await db_session.refresh(dc)
    await db_session.refresh(carrier)
    await db_session.refresh(st)

    order = Order(
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=st.shipment_type_code,
        brand_order_ref=order_ref,
        destination_country="CO",
        destination_region="Cundinamarca",
        freight_value=Decimal("20000.00"),
        status=status,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    # Dispatch record on Saturday morning
    effective_dispatch = dispatch_dt or datetime(2026, 10, 24, 11, 0, 0, tzinfo=UTC)
    dispatch = Dispatch(
        dc_id=dc.dc_id,
        carrier_id=carrier.carrier_id,
        dispatched_at=effective_dispatch,
    )
    db_session.add(dispatch)
    await db_session.commit()
    await db_session.refresh(dispatch)

    label = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number=f"TRK-{order_ref}",
        dispatch_id=dispatch.dispatch_id,
        status=status,
    )
    db_session.add(label)
    await db_session.commit()
    await db_session.refresh(label)

    return order, label, carrier


@pytest.mark.asyncio
async def test_scn08_fourteen_business_hours_remaining_in_transit_is_at_risk(
    db_session,
    at_risk_service_instance: AtRiskService,
) -> None:
    """SCN-08: Dispatched on Saturday, 14 business hours to deadline, in transit -> AT RISK.

    - Saturday Oct 24, 2026: Dispatched before cutoff.
    - Sunday Oct 25: Excluded (0h).
    - Monday Oct 26: Holiday in CO (0h).
    - Tuesday Oct 27: Business day 1.
    - Wednesday Oct 28: Business day 2 -> SLA due at end of Wednesday.
    - Evaluation time: Wednesday Oct 28 at 10:00:00 (14 business hours remaining before deadline).
    - Since 14.0h <= 24h and status is IN_TRANSIT (not OUT_FOR_DELIVERY) -> AT RISK.
    """
    service = at_risk_service_instance

    # Dispatch Saturday morning Oct 24 at 16:00 UTC (11:00 AM local)
    dispatch_dt = datetime(2026, 10, 24, 16, 0, 0, tzinfo=UTC)
    order, label, _ = await _seed_test_order(
        db_session, status="IN_TRANSIT", dispatch_dt=dispatch_dt, order_ref="SCN-08-REF"
    )

    # Evaluate at Wednesday Oct 28 at 15:00 UTC (10:00 AM local Colombia): 14h left until end of day
    eval_time = datetime(2026, 10, 28, 15, 0, 0, tzinfo=UTC)
    result = await service.evaluate_and_update_order_risk(
        db_session, order.order_id, current_time=eval_time
    )

    assert result.is_at_risk is True
    assert result.business_hours_remaining is not None
    assert result.business_hours_remaining <= 24.0
    assert any("FEWER_THAN_24_BUSINESS_HOURS_REMAINING" in r for r in result.at_risk_reasons)
    assert order.is_at_risk is True
    assert "FEWER_THAN_24_BUSINESS_HOURS_REMAINING" in (order.at_risk_reason or "")


@pytest.mark.asyncio
async def test_scn09_same_dates_but_out_for_delivery_is_not_at_risk(
    db_session,
    at_risk_service_instance: AtRiskService,
) -> None:
    """SCN-09: Same dates as SCN-08 but already out for delivery -> NOT AT RISK.

    Even if 14 business hours remain, an order marked OUT_FOR_DELIVERY is on its final
    distribution route and is exempt from the 24-business-hour at-risk flag.
    """
    service = at_risk_service_instance

    dispatch_dt = datetime(2026, 10, 24, 16, 0, 0, tzinfo=UTC)
    order, label, _ = await _seed_test_order(
        db_session, status="OUT_FOR_DELIVERY", dispatch_dt=dispatch_dt, order_ref="SCN-09-REF"
    )

    eval_time = datetime(2026, 10, 28, 15, 0, 0, tzinfo=UTC)
    result = await service.evaluate_and_update_order_risk(
        db_session, order.order_id, current_time=eval_time
    )

    assert result.is_at_risk is False
    assert result.at_risk_reasons == []
    assert order.is_at_risk is False
    assert order.at_risk_reason is None


@pytest.mark.asyncio
async def test_scn10_unresolved_exception_open_for_16_hours_is_at_risk(
    db_session,
    at_risk_service_instance: AtRiskService,
) -> None:
    """SCN-10: An issue (EXCEPTION) open for 16 hours (> 12h threshold) -> AT RISK."""
    service = at_risk_service_instance

    dispatch_dt = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
    order, label, carrier = await _seed_test_order(
        db_session, status="EXCEPTION", dispatch_dt=dispatch_dt, order_ref="SCN-10-REF"
    )

    # Record tracking event showing exception occurred 16 hours ago
    exception_start = datetime(2026, 10, 21, 0, 0, 0, tzinfo=UTC)
    eval_time = exception_start + timedelta(hours=16)

    event = TrackingEvent(
        carrier_id=carrier.carrier_id,
        label_id=label.label_id,
        tracking_number=label.tracking_number,
        raw_status="Held in customs",
        canonical_status="EXCEPTION",
        event_timestamp=exception_start,
    )
    db_session.add(event)
    await db_session.commit()

    result = await service.evaluate_and_update_order_risk(
        db_session, order.order_id, current_time=eval_time
    )

    assert result.is_at_risk is True
    assert result.open_exception_duration_hours == 16.0
    assert any("UNRESOLVED_EXCEPTION_EXCEEDED_12_HOURS" in r for r in result.at_risk_reasons)
    assert order.is_at_risk is True


@pytest.mark.asyncio
async def test_exception_open_for_5_hours_is_not_at_risk(
    db_session,
    at_risk_service_instance: AtRiskService,
) -> None:
    """An exception open for 5 hours is within the 12-hour tolerance threshold."""
    service = at_risk_service_instance

    dispatch_dt = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
    order, label, carrier = await _seed_test_order(
        db_session, status="EXCEPTION", dispatch_dt=dispatch_dt, order_ref="EXC-5H-REF"
    )

    exception_start = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    eval_time = exception_start + timedelta(hours=5)

    event = TrackingEvent(
        carrier_id=carrier.carrier_id,
        label_id=label.label_id,
        tracking_number=label.tracking_number,
        raw_status="Damaged box",
        canonical_status="EXCEPTION",
        event_timestamp=exception_start,
    )
    db_session.add(event)
    await db_session.commit()

    result = await service.evaluate_order_risk(db_session, order.order_id, current_time=eval_time)

    assert result.open_exception_duration_hours == 5.0
    assert not any("UNRESOLVED_EXCEPTION_EXCEEDED_12_HOURS" in r for r in result.at_risk_reasons)


@pytest.mark.asyncio
async def test_terminal_delivered_order_is_never_at_risk(
    db_session,
    at_risk_service_instance: AtRiskService,
) -> None:
    """An order already DELIVERED is terminal and can never be at risk."""
    service = at_risk_service_instance

    dispatch_dt = datetime(2026, 10, 10, 8, 0, 0, tzinfo=UTC)
    order, label, _ = await _seed_test_order(
        db_session, status="DELIVERED", dispatch_dt=dispatch_dt, order_ref="DELIV-REF"
    )

    eval_time = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
    result = await service.evaluate_and_update_order_risk(
        db_session, order.order_id, current_time=eval_time
    )

    assert result.is_at_risk is False
    assert result.at_risk_reasons == []


@pytest.mark.asyncio
async def test_epic1_normalize_event_automatically_updates_risk(
    db_session,
) -> None:
    """Epic 1 Integration: normalize_event updates tracking events and risk automatically."""
    # Seed order and label in CREATED
    order, label, carrier = await _seed_test_order(
        db_session, status="CREATED", order_ref="EPIC1-AUTO-RISK"
    )

    # Seed state mapping for SENT -> IN_TRANSIT
    mapping = StateMapping(
        carrier_id=carrier.carrier_id,
        raw_status="SENT",
        canonical_status="IN_TRANSIT",
    )
    db_session.add(mapping)
    await db_session.commit()
    state_mapping_cache.invalidate()

    # 1. First event: Carrier reports IN_TRANSIT
    evt_time = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)
    norm_res = await normalize_event(
        db=db_session,
        carrier_identifier=carrier.carrier_id,
        tracking_number=label.tracking_number,
        raw_status="SENT",
        occurred_at=evt_time,
    )
    assert norm_res.success is True

    # Order was refreshed and has TrackingEvent in DB
    refreshed_order = await db_session.get(Order, order.order_id)
    assert refreshed_order.status == "IN_TRANSIT"

    # Verify TrackingEvent row was created
    events = (
        (
            await db_session.execute(
                select(TrackingEvent).where(TrackingEvent.label_id == label.label_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].canonical_status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_evaluate_all_active_orders(
    db_session,
    at_risk_service_instance: AtRiskService,
) -> None:
    service = at_risk_service_instance

    # Seed 1 order delivered and 1 order in transit
    await _seed_test_order(db_session, status="DELIVERED", order_ref="BULK-DELIV")
    order_transit, _, _ = await _seed_test_order(
        db_session, status="IN_TRANSIT", order_ref="BULK-TRANSIT"
    )

    results = await service.evaluate_all_active_orders(db_session)
    # Only active non-terminal order is evaluated
    assert len(results) == 1
    assert results[0].order_id == order_transit.order_id
