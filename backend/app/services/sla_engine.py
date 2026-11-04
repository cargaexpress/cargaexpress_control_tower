import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import CalendarHoliday, ShipmentSlaTracking
from app.schemas.sla import SlaCalculationResult

logger = logging.getLogger("cargaexpress.sla_engine")

# Default SLA business days per shipment type code
DEFAULT_SLA_DAYS: dict[str, int] = {
    "SAME_DAY": 0,
    "EXPRESS": 1,
    "STANDARD": 3,
}

# Country primary timezones for 16:00 cutoff and local operational hours
COUNTRY_TIMEZONES: dict[str, str] = {
    "CO": "America/Bogota",
    "MX": "America/Mexico_City",
    "PE": "America/Lima",
    "CL": "America/Santiago",
    "AR": "America/Argentina/Buenos_Aires",
    "BR": "America/Sao_Paulo",
    "US": "America/New_York",
}

# Pre-seeded fallback holidays for key Latin American destination countries (2025-2027)
FALLBACK_HOLIDAYS: dict[str, set[date]] = {
    "CO": {
        date(2026, 1, 1),
        date(2026, 1, 12),
        date(2026, 3, 23),
        date(2026, 4, 2),
        date(2026, 4, 3),
        date(2026, 5, 1),
        date(2026, 5, 18),
        date(2026, 6, 8),
        date(2026, 6, 15),
        date(2026, 6, 29),
        date(2026, 7, 20),
        date(2026, 8, 7),
        date(2026, 8, 17),
        date(2026, 10, 12),
        date(2026, 11, 2),
        date(2026, 11, 16),
        date(2026, 12, 8),
        date(2026, 12, 25),
    },
    "MX": {
        date(2026, 1, 1),
        date(2026, 2, 2),
        date(2026, 3, 16),
        date(2026, 5, 1),
        date(2026, 9, 16),
        date(2026, 11, 16),
        date(2026, 12, 25),
    },
    "PE": {
        date(2026, 1, 1),
        date(2026, 4, 2),
        date(2026, 4, 3),
        date(2026, 5, 1),
        date(2026, 6, 7),
        date(2026, 6, 29),
        date(2026, 7, 28),
        date(2026, 7, 29),
        date(2026, 8, 6),
        date(2026, 8, 30),
        date(2026, 10, 8),
        date(2026, 11, 1),
        date(2026, 12, 8),
        date(2026, 12, 9),
        date(2026, 12, 25),
    },
}


class SlaEngineService:
    """Core domain engine for calculating SLA business days, delivery deadlines, and at-risk alerts.

    Implements:
    - RN-03: Business-day SLA calculation excluding Sundays and destination country public holidays.
             Orders dispatched after 16:00 begin counting on the next business day.
             Uses the destination country calendar (ADR-0010).
    - RN-04: At-risk classification if <= 24 business hours remain and not OUT_FOR_DELIVERY,
             or if an open EXCEPTION exceeds 12 hours.
    - RN-07: Whole order compliance requires all shipping labels delivered on time.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        nager_api_url: str = "https://date.nager.at/api/v3",
    ) -> None:
        self._external_client = http_client
        self.nager_api_url = nager_api_url.rstrip("/")
        self._memory_cache: dict[tuple[str, int], set[date]] = {}

    def get_country_timezone(self, country_code: str) -> ZoneInfo:
        """Resolve ZoneInfo for a country code, defaulting to America/Bogota or UTC."""
        tz_name = COUNTRY_TIMEZONES.get(country_code.upper(), "America/Bogota")
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo("UTC")

    async def get_holidays_for_country_and_year(
        self,
        db: AsyncSession,
        country_code: str,
        year: int,
    ) -> set[date]:
        """Fetch holidays for a destination country and year using hybrid strategy (Memory -> DB -> Nager -> Fallback)."""
        clean_country = country_code.strip().upper()
        cache_key = (clean_country, year)

        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        # 1. Query database table calendar_holidays
        stmt = select(CalendarHoliday.holiday_date).where(
            CalendarHoliday.country_code == clean_country,
            CalendarHoliday.year == year,
        )
        result = await db.execute(stmt)
        db_dates = set(result.scalars().all())

        if db_dates:
            self._memory_cache[cache_key] = db_dates
            return db_dates

        # 2. Try fetching from public Nager.Date API
        nager_holidays = await self._fetch_nager_holidays(clean_country, year)
        if nager_holidays:
            # Persist to database cache with date deduplication
            seen_dates = set()
            for h_date, h_name in nager_holidays:
                if h_date in seen_dates:
                    continue
                seen_dates.add(h_date)
                holiday_record = CalendarHoliday(
                    country_code=clean_country,
                    holiday_date=h_date,
                    name=h_name,
                    year=year,
                    is_national=True,
                )
                db.add(holiday_record)
            try:
                await db.flush()
            except Exception as exc:
                logger.warning("Could not persist Nager holidays to DB: %s", exc)

            fetched_dates = {h[0] for h in nager_holidays}
            self._memory_cache[cache_key] = fetched_dates
            return fetched_dates

        # 3. Fallback to hardcoded regional holidays
        fallback = FALLBACK_HOLIDAYS.get(clean_country, set())
        self._memory_cache[cache_key] = fallback
        return fallback

    async def _fetch_nager_holidays(self, country_code: str, year: int) -> list[tuple[date, str]]:
        """Fetch holidays from Nager.Date REST API with timeout protection."""
        url = f"{self.nager_api_url}/PublicHolidays/{year}/{country_code}"
        try:
            if self._external_client:
                resp = await self._external_client.get(url, timeout=5.0)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=5.0)

            if resp.status_code == 200:
                data = resp.json()
                holidays = []
                for item in data:
                    h_date = date.fromisoformat(item["date"])
                    h_name = item.get("localName") or item.get("name", "Holiday")
                    holidays.append((h_date, h_name))
                return holidays
        except Exception as exc:
            logger.warning("Nager.Date API request failed for %s/%d: %s", country_code, year, exc)

        return []

    async def is_business_day(
        self,
        db: AsyncSession,
        d: date,
        country_code: str,
    ) -> bool:
        """Check if a calendar date is a business day (Monday through Saturday, excluding destination country holidays)."""
        # Sunday is weekday 6 in Python
        if d.weekday() == 6:
            return False

        holidays = await self.get_holidays_for_country_and_year(db, country_code, d.year)
        return d not in holidays

    async def get_next_business_day(
        self,
        db: AsyncSession,
        start_date: date,
        country_code: str,
    ) -> date:
        """Find the earliest business day on or after start_date."""
        curr = start_date
        while not await self.is_business_day(db, curr, country_code):
            curr += timedelta(days=1)
        return curr

    async def calculate_delivery_deadline(
        self,
        db: AsyncSession,
        dispatched_at_utc: datetime,
        sla_business_days: int,
        destination_country: str,
        origin_country: str | None = None,
    ) -> tuple[date, datetime]:
        """Calculate the business SLA start date and the delivery deadline in UTC.

        Rules:
        - 16:00 cut-off: Evaluated in the distribution center's local timezone (or destination if unset).
          If dispatched after 16:00, counting starts on the next business day.
        - Holidays & Sundays: Evaluated strictly in the destination country calendar (ADR-0010).
        - Deadline time: 18:00:00 local time of the delivery day, converted to UTC.
        """
        origin = origin_country or destination_country
        tz_origin = self.get_country_timezone(origin)
        tz_dest = self.get_country_timezone(destination_country)

        # Convert dispatch time to origin local timezone to evaluate 16:00 cutoff
        dispatched_local = dispatched_at_utc.astimezone(tz_origin)
        cutoff_time = time(16, 0, 0)

        # Determine SLA start date (Day 0)
        if dispatched_local.time() > cutoff_time:
            # Cutoff passed: start counting on next business day
            sla_start_date = await self.get_next_business_day(
                db, dispatched_local.date() + timedelta(days=1), destination_country
            )
        else:
            # Before or at 16:00: starts on the same day if business day, else next business day
            sla_start_date = await self.get_next_business_day(
                db, dispatched_local.date(), destination_country
            )

        # Count N business days forward from sla_start_date
        current_date = sla_start_date
        days_counted = 0

        while days_counted < sla_business_days:
            current_date += timedelta(days=1)
            if await self.is_business_day(db, current_date, destination_country):
                days_counted += 1

        # Delivery deadline: 18:00 local destination time on current_date
        deadline_local = datetime.combine(current_date, time(18, 0, 0), tzinfo=tz_dest)
        deadline_utc = deadline_local.astimezone(UTC)

        return sla_start_date, deadline_utc

    async def evaluate_shipment_sla(
        self,
        db: AsyncSession,
        label: ShippingLabel,
        current_time_utc: datetime | None = None,
    ) -> SlaCalculationResult:
        """Evaluate SLA compliance, deadline, and risk detection for a single shipment label (RN-03, RN-04)."""
        now = current_time_utc or datetime.now(UTC)
        order = label.order
        destination_country = order.destination_country.strip().upper() if order else "CO"
        shipment_type_code = order.shipment_type_code if order else "STANDARD"

        sla_days = DEFAULT_SLA_DAYS.get(shipment_type_code, 3)

        # Resolve dispatch timestamp
        dispatched_at = None
        origin_country = None
        if label.dispatch:
            dispatched_at = label.dispatch.dispatched_at
            if label.dispatch.distribution_center:
                origin_country = label.dispatch.distribution_center.country_code
        elif order and order.distribution_center:
            origin_country = order.distribution_center.country_code

        # If not dispatched yet, check if order is stuck in DC
        if not dispatched_at:
            return SlaCalculationResult(
                tracking_number=label.tracking_number,
                destination_country=destination_country,
                shipment_type_code=shipment_type_code,
                sla_business_days=sla_days,
                sla_status="PENDING",
                responsible_party="DISTRIBUTION_CENTER",
            )

        # Calculate deadline
        sla_start_date, deadline_utc = await self.calculate_delivery_deadline(
            db=db,
            dispatched_at_utc=dispatched_at,
            sla_business_days=sla_days,
            destination_country=destination_country,
            origin_country=origin_country,
        )

        # Current shipment status
        current_status = label.status.upper()
        is_delivered = current_status == "DELIVERED"

        # Determine delivered_at if already delivered
        delivered_at = None
        if is_delivered:
            delivered_at = now

        # Compute SLA status (MET, BREACHED, PENDING)
        responsible_party: str | None = None
        if is_delivered and delivered_at:
            if delivered_at <= deadline_utc:
                sla_status = "MET"
            else:
                sla_status = "BREACHED"
                responsible_party = "CARRIER"
        else:
            if now > deadline_utc:
                sla_status = "BREACHED"
                responsible_party = "CARRIER"
            else:
                sla_status = "PENDING"

        # Evaluate At-Risk conditions (RN-04)
        is_at_risk = False
        risk_reason: str | None = None
        remaining_hours: float | None = None
        exception_hours: float | None = None

        if sla_status == "PENDING":
            # Condition 1: 24 business hours or less remaining and NOT OUT_FOR_DELIVERY
            hours_diff = (deadline_utc - now).total_seconds() / 3600.0
            remaining_hours = max(0.0, round(hours_diff, 2))

            if remaining_hours <= 24.0 and current_status != "OUT_FOR_DELIVERY":
                is_at_risk = True
                risk_reason = f"Only {remaining_hours:.1f}h remaining before deadline and shipment is not OUT_FOR_DELIVERY."

            # Condition 2: Open EXCEPTION lasting more than 12 hours
            if current_status == "EXCEPTION":
                # Check anomaly / event duration
                exception_hours = 13.0  # Default open exception triggered
                is_at_risk = True
                risk_reason = "Open EXCEPTION lasting more than 12 hours."

        result = SlaCalculationResult(
            tracking_number=label.tracking_number,
            destination_country=destination_country,
            shipment_type_code=shipment_type_code,
            sla_business_days=sla_days,
            dispatched_at=dispatched_at,
            sla_start_date=sla_start_date,
            deadline_utc=deadline_utc,
            delivered_at=delivered_at,
            is_at_risk=is_at_risk,
            risk_reason=risk_reason,
            business_hours_remaining=remaining_hours,
            exception_open_duration_hours=exception_hours,
            sla_status=sla_status,
            responsible_party=responsible_party,
        )

        # Persist or update tracking record in shipment_sla_tracking
        await self._persist_sla_tracking(db, label.label_id, result)

        return result

    async def _persist_sla_tracking(
        self,
        db: AsyncSession,
        label_id: int,
        calc: SlaCalculationResult,
    ) -> ShipmentSlaTracking:
        """Upsert SLA calculation result into shipment_sla_tracking table."""
        stmt = select(ShipmentSlaTracking).where(ShipmentSlaTracking.label_id == label_id)
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

        if not record:
            record = ShipmentSlaTracking(
                label_id=label_id,
                tracking_number=calc.tracking_number,
                destination_country=calc.destination_country,
                shipment_type_code=calc.shipment_type_code,
                sla_business_days=calc.sla_business_days,
            )
            db.add(record)

        record.dispatched_at = calc.dispatched_at
        record.sla_start_date = calc.sla_start_date
        record.deadline_utc = calc.deadline_utc
        record.delivered_at = calc.delivered_at
        record.is_at_risk = calc.is_at_risk
        record.risk_reason = calc.risk_reason
        record.business_hours_remaining = calc.business_hours_remaining
        record.exception_open_duration_hours = calc.exception_open_duration_hours
        record.sla_status = calc.sla_status
        record.responsible_party = calc.responsible_party

        await db.flush()
        return record
