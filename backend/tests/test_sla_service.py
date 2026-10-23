from datetime import UTC, date, datetime

import pytest

from app.services.holiday_service import HolidayService
from app.services.sla_service import SLAService


@pytest.fixture
def mock_holiday_service() -> HolidayService:
    service = HolidayService()
    service.clear_cache()
    # Preload Monday 2026-10-26 as holiday in CO and PE, but NOT in MX
    service.preload_holidays("CO", 2026, ["2026-10-26"])
    service.preload_holidays("PE", 2026, ["2026-10-26"])
    service.preload_holidays("MX", 2026, [])
    return service


@pytest.fixture
def sla_service_instance(mock_holiday_service: HolidayService) -> SLAService:
    return SLAService(holidays=mock_holiday_service)


@pytest.mark.asyncio
async def test_acceptance_criteria_friday_5pm_plus_monday_holiday_due_wednesday(
    sla_service_instance: SLAService,
) -> None:
    """Acceptance Criteria:

    Friday 5:00 PM dispatch (after 16:00 cutoff) with 2-day SLA and Monday holiday.
    - Friday 17:00: Dispatch happens after 16:00 cutoff.
    - Saturday: Day 0 (counting starts on next business day).
    - Sunday: Excluded (does not count).
    - Monday: Holiday (does not count).
    - Tuesday: Business day 1.
    - Wednesday: Business day 2 -> SLA due Wednesday.
    """
    service = sla_service_instance

    # Friday Oct 23, 2026 at 17:00 (5:00 PM) in America/Bogota (UTC-5 -> 22:00 UTC)
    dispatched_at = datetime(2026, 10, 23, 22, 0, 0, tzinfo=UTC)

    result = await service.calculate_sla_deadline(
        dispatched_at=dispatched_at,
        sla_business_days=2,
        destination_country="CO",
        origin_country="CO",
    )

    assert result.is_after_cutoff is True
    assert result.counting_start_date == date(2026, 10, 24)  # Saturday (Day 0)
    assert date(2026, 10, 25) in result.excluded_dates  # Sunday excluded
    assert date(2026, 10, 26) in result.excluded_dates  # Monday Holiday excluded
    assert result.business_days_counted == [date(2026, 10, 27), date(2026, 10, 28)]  # Tue, Wed
    assert result.deadline_date == date(2026, 10, 28)  # Due Wednesday!
    assert result.deadline_date.strftime("%A") == "Wednesday"


@pytest.mark.asyncio
async def test_friday_dispatch_after_cutoff_exact_local_hour(
    sla_service_instance: SLAService,
) -> None:
    service = sla_service_instance

    # In America/Bogota (UTC-5), 17:00 local is 22:00 UTC
    # Friday Oct 23, 2026, 17:00 local time (5:00 PM)
    dispatched_at = datetime(2026, 10, 23, 22, 0, 0, tzinfo=UTC)

    result = await service.calculate_sla_deadline(
        dispatched_at=dispatched_at,
        sla_business_days=2,
        destination_country="CO",
        origin_country="CO",
    )

    assert result.is_after_cutoff is True
    assert result.counting_start_date == date(2026, 10, 24)  # Saturday (Day 0)
    assert result.business_days_counted == [date(2026, 10, 27), date(2026, 10, 28)]  # Tue, Wed
    assert date(2026, 10, 25) in result.excluded_dates  # Sunday
    assert date(2026, 10, 26) in result.excluded_dates  # Monday Holiday
    assert result.deadline_date == date(2026, 10, 28)  # Wednesday!
    assert result.deadline_date.strftime("%A") == "Wednesday"


@pytest.mark.asyncio
async def test_friday_dispatch_before_cutoff_due_tuesday(
    sla_service_instance: SLAService,
) -> None:
    """Friday 3:00 PM dispatch (before 16:00 cutoff):

    - Friday 15:00: Dispatch happens before 16:00 cutoff.
    - Friday: Day 0 (counting starts same day).
    - Saturday: Business day 1.
    - Sunday: Excluded.
    - Monday: Holiday, excluded.
    - Tuesday: Business day 2 -> SLA due Tuesday.
    """
    service = sla_service_instance

    # In America/Bogota (UTC-5), 15:00 local is 20:00 UTC
    dispatched_at = datetime(2026, 10, 23, 20, 0, 0, tzinfo=UTC)

    result = await service.calculate_sla_deadline(
        dispatched_at=dispatched_at,
        sla_business_days=2,
        destination_country="CO",
        origin_country="CO",
    )

    assert result.is_after_cutoff is False
    assert result.counting_start_date == date(2026, 10, 23)  # Friday
    assert result.business_days_counted == [date(2026, 10, 24), date(2026, 10, 27)]  # Sat, Tue
    assert result.deadline_date == date(2026, 10, 27)  # Tuesday!
    assert result.deadline_date.strftime("%A") == "Tuesday"


@pytest.mark.asyncio
async def test_dispatched_on_saturday_before_and_after_cutoff(
    sla_service_instance: SLAService,
) -> None:
    service = sla_service_instance

    # Saturday Oct 24, 2026 at 11:00 AM local (16:00 UTC) -> before 16:00 cutoff
    sat_morning = datetime(2026, 10, 24, 16, 0, 0, tzinfo=UTC)
    res_morning = await service.calculate_sla_deadline(
        dispatched_at=sat_morning,
        sla_business_days=2,
        destination_country="CO",
    )
    assert res_morning.is_after_cutoff is False
    assert res_morning.counting_start_date == date(2026, 10, 24)  # Saturday
    assert res_morning.deadline_date == date(2026, 10, 28)  # Wednesday (Monday is holiday)

    # Saturday Oct 24, 2026 at 17:00 local (22:00 UTC) -> after 16:00 cutoff
    sat_evening = datetime(2026, 10, 24, 22, 0, 0, tzinfo=UTC)
    res_evening = await service.calculate_sla_deadline(
        dispatched_at=sat_evening,
        sla_business_days=2,
        destination_country="CO",
    )
    assert res_evening.is_after_cutoff is True
    # Sunday is skipped, Monday is holiday (skipped), so counting starts Tuesday!
    assert res_evening.counting_start_date == date(2026, 10, 27)
    assert res_evening.business_days_counted == [date(2026, 10, 28), date(2026, 10, 29)]
    assert res_evening.deadline_date == date(2026, 10, 29)  # Thursday


@pytest.mark.asyncio
async def test_dispatched_on_sunday_starts_next_business_day(
    sla_service_instance: SLAService,
) -> None:
    service = sla_service_instance

    # Sunday Oct 25, 2026 at 14:00 local
    sun_dispatch = datetime(2026, 10, 25, 19, 0, 0, tzinfo=UTC)
    res = await service.calculate_sla_deadline(
        dispatched_at=sun_dispatch,
        sla_business_days=2,
        destination_country="CO",
    )
    # Since Monday is holiday, next business day is Tuesday
    assert res.counting_start_date == date(2026, 10, 27)
    assert res.deadline_date == date(2026, 10, 29)


@pytest.mark.asyncio
async def test_scn11_dispatched_on_public_holiday(
    sla_service_instance: SLAService,
) -> None:
    """SCN-11: Order dispatched on a public holiday."""
    service = sla_service_instance

    # Monday Oct 26, 2026 (public holiday in CO) at 10:00 local
    holiday_dispatch = datetime(2026, 10, 26, 15, 0, 0, tzinfo=UTC)
    res = await service.calculate_sla_deadline(
        dispatched_at=holiday_dispatch,
        sla_business_days=2,
        destination_country="CO",
    )
    # Starts on Tuesday Oct 27
    assert res.counting_start_date == date(2026, 10, 27)
    assert res.deadline_date == date(2026, 10, 29)


@pytest.mark.asyncio
async def test_scn12_cross_country_destination_calendar_rule(
    sla_service_instance: SLAService,
) -> None:
    """SCN-12: DC in Mexico (MX), destination Peru (PE).

    Monday is a holiday in PE, but NOT in MX.
    Per RN-03 / ADR-0010, destination calendar PE must be used.
    """
    service = sla_service_instance

    # Friday Oct 23 at 17:00 local MX time (23:00 UTC)
    dispatch_cross = datetime(2026, 10, 23, 23, 0, 0, tzinfo=UTC)

    res = await service.calculate_sla_deadline(
        dispatched_at=dispatch_cross,
        sla_business_days=2,
        destination_country="PE",
        origin_country="MX",
    )

    assert res.is_after_cutoff is True
    # Destination PE holiday on Monday is respected
    assert date(2026, 10, 26) in res.excluded_dates
    assert res.deadline_date == date(2026, 10, 28)  # Wednesday!


@pytest.mark.asyncio
async def test_zero_sla_business_days(sla_service_instance: SLAService) -> None:
    service = sla_service_instance
    dispatch = datetime(2026, 10, 23, 15, 0, 0, tzinfo=UTC)  # Friday morning
    res = await service.calculate_sla_deadline(
        dispatched_at=dispatch,
        sla_business_days=0,
        destination_country="CO",
    )
    assert res.deadline_date == res.counting_start_date
    assert res.business_days_counted == []


@pytest.mark.asyncio
async def test_exact_cutoff_boundary_16_00_vs_15_59(
    sla_service_instance: SLAService,
) -> None:
    service = sla_service_instance

    # 15:59:59 in UTC (using destination country with UTC offset 0 for boundary precision)
    before_dt = datetime(2026, 10, 23, 15, 59, 59, tzinfo=UTC)
    res_before = await service.calculate_sla_deadline(
        dispatched_at=before_dt,
        sla_business_days=1,
        destination_country="GB",  # UTC
        origin_country="GB",
    )
    assert res_before.is_after_cutoff is False
    assert res_before.counting_start_date == date(2026, 10, 23)

    # 16:00:00 exact
    exact_dt = datetime(2026, 10, 23, 16, 0, 0, tzinfo=UTC)
    res_exact = await service.calculate_sla_deadline(
        dispatched_at=exact_dt,
        sla_business_days=1,
        destination_country="GB",
        origin_country="GB",
    )
    assert res_exact.is_after_cutoff is True
    assert res_exact.counting_start_date == date(2026, 10, 24)


@pytest.mark.asyncio
async def test_year_boundary_new_year_holiday(sla_service_instance: SLAService) -> None:
    service = sla_service_instance
    # Preload Jan 1, 2027 as holiday
    service.holiday_service.preload_holidays("CO", 2027, ["2027-01-01"])

    # Dispatched Thursday Dec 31, 2026 at 17:00 (after cutoff, 22:00 UTC)
    dispatch_nye = datetime(2026, 12, 31, 22, 0, 0, tzinfo=UTC)
    res = await service.calculate_sla_deadline(
        dispatched_at=dispatch_nye,
        sla_business_days=2,
        destination_country="CO",
    )
    # Dec 31 is Thursday. Next business day after cutoff: Friday Jan 1 is holiday!
    # Saturday Jan 2 is business day (Day 0).
    # Sunday Jan 3 is excluded.
    # Monday Jan 4 is Business Day 1.
    # Tuesday Jan 5 is Business Day 2 -> Due Tuesday Jan 5, 2027.
    assert res.counting_start_date == date(2027, 1, 2)
    assert res.deadline_date == date(2027, 1, 5)


@pytest.mark.asyncio
async def test_calculate_order_sla_with_database(
    db_session,
    sla_service_instance: SLAService,
) -> None:
    from decimal import Decimal

    from app.models.brand import Brand
    from app.models.carrier import Carrier
    from app.models.dispatch import Dispatch
    from app.models.distribution_center import DistributionCenter
    from app.models.order import Order
    from app.models.shipment_type import ShipmentType
    from app.models.shipping_label import ShippingLabel

    # Seed entities
    brand = Brand(name="SLA Test Brand", tier="standard", is_active=True)
    dc = DistributionCenter(code="DC-BOG", name="Bogota DC", city="Bogota", country_code="CO")
    carrier = Carrier(name="Test Carrier", integration_type="WEBHOOK", status="ACTIVE")
    st = ShipmentType(shipment_type_code="SLA_STD", description="SLA Standard")
    db_session.add_all([brand, dc, carrier, st])
    await db_session.commit()

    # Create Order
    order = Order(
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=st.shipment_type_code,
        brand_order_ref="SLA-ORDER-001",
        destination_country="CO",
        destination_region="Cundinamarca",
        freight_value=Decimal("15000.00"),
        status="DISPATCHED",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    # Create Dispatch record on Friday Oct 23 at 17:00 local (22:00 UTC)
    dispatch_dt = datetime(2026, 10, 23, 22, 0, 0, tzinfo=UTC)
    dispatch = Dispatch(
        dc_id=dc.dc_id,
        carrier_id=carrier.carrier_id,
        dispatched_at=dispatch_dt,
    )
    db_session.add(dispatch)
    await db_session.commit()
    await db_session.refresh(dispatch)

    # Attach shipping label with dispatch_id
    label = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRACK-SLA-999",
        dispatch_id=dispatch.dispatch_id,
        status="IN_TRANSIT",
    )
    db_session.add(label)
    await db_session.commit()

    # Calculate SLA from DB Order
    result = await sla_service_instance.calculate_order_sla(
        db_session, order.order_id, sla_business_days=2
    )
    assert result.is_after_cutoff is True
    assert result.deadline_date == date(2026, 10, 28)  # Due Wednesday!

    # Test non-existent order raises ValueError
    with pytest.raises(ValueError, match="not found"):
        await sla_service_instance.calculate_order_sla(db_session, 999999)
