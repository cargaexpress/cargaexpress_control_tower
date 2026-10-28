import logging
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.dispatch import Dispatch
from app.models.order import Order
from app.schemas.sla import SLADeadlineResult
from app.services.holiday_service import HolidayService, holiday_service

logger = logging.getLogger(__name__)

# Standard capital/commercial timezones per country code
COUNTRY_TIMEZONES: dict[str, str] = {
    "CO": "America/Bogota",
    "MX": "America/Mexico_City",
    "PE": "America/Lima",
    "CL": "America/Santiago",
    "AR": "America/Argentina/Buenos_Aires",
    "BR": "America/Sao_Paulo",
    "US": "America/New_York",
    "EC": "America/Guayaquil",
    "PA": "America/Panama",
    "CR": "America/Costa_Rica",
    "GT": "America/Guatemala",
    "UY": "America/Montevideo",
}

# Fixed fallback UTC offsets in hours for offline or minimal environments
COUNTRY_OFFSETS: dict[str, int] = {
    "CO": -5,
    "PE": -5,
    "EC": -5,
    "PA": -5,
    "MX": -6,
    "CR": -6,
    "GT": -6,
    "CL": -4,
    "AR": -3,
    "BR": -3,
    "UY": -3,
    "US": -5,
}


class SLAService:
    """Service to calculate SLA deadlines in business days according to RN-03 and ADR-0010."""

    def __init__(self, holidays: HolidayService | None = None) -> None:
        self.holiday_service = holidays or holiday_service
        self.cutoff_hour = settings.sla_cutoff_hour

    def get_timezone_for_country(self, country_code: str | None) -> tzinfo:
        """Resolve timezone for an ISO country code, with fallback to UTC."""
        if not country_code:
            return UTC
        code = country_code.strip().upper()
        tz_name = COUNTRY_TIMEZONES.get(code)
        if tz_name:
            try:
                return ZoneInfo(tz_name)
            except Exception:
                pass
        if code in COUNTRY_OFFSETS:
            return timezone(timedelta(hours=COUNTRY_OFFSETS[code]))
        return UTC

    async def is_business_day(self, target_date: date, country_code: str) -> bool:
        """Check if target_date is a business day for the given country.

        Business days are Monday through Saturday (weekday 0-5), excluding Sundays
        and public holidays of the destination country.
        """
        # Sunday is never a business day (weekday 6)
        if target_date.weekday() == 6:
            return False

        # Exclude destination country public holidays
        if await self.holiday_service.is_holiday(country_code, target_date):
            return False

        return True

    async def get_next_business_day(self, start_date: date, country_code: str) -> date:
        """Find the earliest business day on or after start_date."""
        current = start_date
        while not await self.is_business_day(current, country_code):
            current += timedelta(days=1)
        return current

    async def calculate_sla_deadline(
        self,
        dispatched_at: datetime,
        sla_business_days: int = 2,
        destination_country: str = "CO",
        origin_country: str | None = None,
    ) -> SLADeadlineResult:
        """Calculate order SLA deadline according to RN-03.

        Rules:
        - Excludes Sundays and destination-country public holidays (Nager.Date F6).
        - Saturdays are business days unless a public holiday.
        - Respects the 16:00 (4:00 PM) cut-off rule:
          - Dispatched before 16:00: counting starts on the same day (if a business day).
          - Dispatched at or after 16:00: counting starts on the next business day.
        - Cut-off is evaluated using the origin DC timezone if provided, or destination timezone (ADR-0010).
        - Holidays and business days are strictly evaluated in destination country calendar (RN-03).
        """
        dest_code = destination_country.strip().upper()
        origin_code = origin_country.strip().upper() if origin_country else None

        # Ensure dispatched_at is timezone-aware in UTC
        if dispatched_at.tzinfo is None:
            utc_dispatch = dispatched_at.replace(tzinfo=UTC)
        else:
            utc_dispatch = dispatched_at.astimezone(UTC)

        # Cut-off timezone: use origin DC timezone if known, else destination timezone
        cutoff_tz = self.get_timezone_for_country(origin_code or dest_code)
        dest_tz = self.get_timezone_for_country(dest_code)

        local_dispatch = utc_dispatch.astimezone(cutoff_tz)
        local_date = local_dispatch.date()
        cutoff_threshold = time(self.cutoff_hour, 0, 0)

        is_after_cutoff = local_dispatch.time() >= cutoff_threshold

        # Determine Day 0 (when business-day counting starts)
        if is_after_cutoff:
            # Dispatched at or after 16:00: starts on next business day
            start_date = await self.get_next_business_day(local_date + timedelta(days=1), dest_code)
        else:
            # Dispatched before 16:00: starts on same day if business day, else next business day
            if await self.is_business_day(local_date, dest_code):
                start_date = local_date
            else:
                start_date = await self.get_next_business_day(
                    local_date + timedelta(days=1), dest_code
                )

        business_days_counted: list[date] = []
        excluded_dates: list[date] = []

        if sla_business_days <= 0:
            deadline_date = start_date
        else:
            curr_date = start_date
            while len(business_days_counted) < sla_business_days:
                curr_date += timedelta(days=1)
                if await self.is_business_day(curr_date, dest_code):
                    business_days_counted.append(curr_date)
                else:
                    excluded_dates.append(curr_date)
            deadline_date = curr_date

        # Compute deadline datetime as end-of-business-day (23:59:59) in destination timezone, converted to UTC
        local_deadline_dt = datetime.combine(deadline_date, time(23, 59, 59), tzinfo=dest_tz)
        utc_deadline_dt = local_deadline_dt.astimezone(UTC)

        return SLADeadlineResult(
            dispatched_at=utc_dispatch,
            sla_business_days=sla_business_days,
            destination_country=dest_code,
            origin_country=origin_code,
            cutoff_hour=self.cutoff_hour,
            is_after_cutoff=is_after_cutoff,
            counting_start_date=start_date,
            deadline_date=deadline_date,
            deadline_datetime=utc_deadline_dt,
            business_days_counted=business_days_counted,
            excluded_dates=excluded_dates,
        )

    async def calculate_order_sla(
        self,
        db: AsyncSession,
        order_id: int,
        sla_business_days: int = 2,
    ) -> SLADeadlineResult:
        """Calculate SLA deadline directly for an Order in the database."""
        stmt = (
            select(Order)
            .where(Order.order_id == order_id)
            .options(
                selectinload(Order.distribution_center),
                selectinload(Order.shipping_labels),
            )
        )
        res = await db.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            raise ValueError(f"Order #{order_id} not found")

        # Find dispatch timestamp: from Dispatch via ShippingLabel or order created_at
        dispatched_at = order.created_at
        origin_country = (
            order.distribution_center.country_code if order.distribution_center else None
        )

        # Check if shipping labels reference a dispatch
        for label in order.shipping_labels:
            if label.dispatch_id:
                dispatch_stmt = select(Dispatch).where(Dispatch.dispatch_id == label.dispatch_id)
                disp_res = await db.execute(dispatch_stmt)
                dispatch = disp_res.scalar_one_or_none()
                if dispatch:
                    dispatched_at = dispatch.dispatched_at
                    break

        return await self.calculate_sla_deadline(
            dispatched_at=dispatched_at,
            sla_business_days=sla_business_days,
            destination_country=order.destination_country,
            origin_country=origin_country,
        )

    async def get_order_sla_summary(
        self,
        db: AsyncSession,
        order: Order,
        current_time: datetime | None = None,
        sla_business_days: int = 2,
    ):
        """Compute complete SLA deadline breakdown, risk status, and compliance status for an order."""
        from app.models.tracking_event import TrackingEvent
        from app.schemas.sla import OrderSLAResponse
        from app.services.at_risk_service import at_risk_service

        sla_res = await self.calculate_order_sla(
            db, order.order_id, sla_business_days=sla_business_days
        )
        risk_res = await at_risk_service.evaluate_order_risk(
            db, order.order_id, current_time=current_time
        )

        now = current_time or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        else:
            now = now.astimezone(UTC)

        deadline_dt = sla_res.deadline_datetime
        if deadline_dt.tzinfo is None:
            deadline_dt = deadline_dt.replace(tzinfo=UTC)
        else:
            deadline_dt = deadline_dt.astimezone(UTC)

        order_status = order.status.upper()
        is_compliant: bool | None = None
        if order_status == "DELIVERED":
            delivered_at: datetime | None = None
            from app.models.shipping_label import ShippingLabel

            lbl_stmt = select(ShippingLabel.label_id).where(
                ShippingLabel.order_id == order.order_id
            )
            lbl_res = await db.execute(lbl_stmt)
            label_ids = list(lbl_res.scalars().all())

            if label_ids:
                evt_stmt = (
                    select(TrackingEvent)
                    .where(
                        TrackingEvent.label_id.in_(label_ids),
                        TrackingEvent.canonical_status == "DELIVERED",
                    )
                    .order_by(TrackingEvent.event_timestamp.desc())
                )
                deliv_evt = (await db.execute(evt_stmt)).scalars().first()
                if deliv_evt:
                    delivered_at = deliv_evt.event_timestamp

            check_dt = delivered_at or order.at_risk_evaluated_at or now
            if check_dt.tzinfo is None:
                check_dt = check_dt.replace(tzinfo=UTC)
            else:
                check_dt = check_dt.astimezone(UTC)

            is_compliant = check_dt <= deadline_dt
            compliance_status = "MET" if is_compliant else "MISSED"
        elif order_status in {"CANCELLED", "RETURNED", "LOST_OR_DAMAGED"}:
            compliance_status = "NOT_APPLICABLE"
            is_compliant = False if order_status in {"LOST_OR_DAMAGED", "RETURNED"} else None
        else:
            # Active in-transit or pending delivery order
            if now > deadline_dt:
                compliance_status = "MISSED"
                is_compliant = False
            else:
                compliance_status = "PENDING"
                is_compliant = None

        return OrderSLAResponse(
            order_id=order.order_id,
            brand_id=order.brand_id,
            status=order.status,
            destination_country=order.destination_country,
            sla_business_days=sla_res.sla_business_days,
            dispatched_at=sla_res.dispatched_at,
            cutoff_hour=sla_res.cutoff_hour,
            is_after_cutoff=sla_res.is_after_cutoff,
            counting_start_date=sla_res.counting_start_date,
            deadline_date=sla_res.deadline_date,
            deadline_datetime=deadline_dt,
            business_days_counted=sla_res.business_days_counted,
            excluded_dates=sla_res.excluded_dates,
            compliance_status=compliance_status,
            is_compliant=is_compliant,
            is_at_risk=risk_res.is_at_risk,
            at_risk_reason=(
                " | ".join(risk_res.at_risk_reasons) if risk_res.at_risk_reasons else None
            ),
            at_risk_reasons=risk_res.at_risk_reasons,
            business_hours_remaining=risk_res.business_hours_remaining,
        )


sla_service = SLAService()
