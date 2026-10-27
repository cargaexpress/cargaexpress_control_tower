import logging
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order
from app.models.tracking_event import TrackingEvent
from app.schemas.at_risk import AtRiskEvaluationResult
from app.services.holiday_service import HolidayService, holiday_service
from app.services.sla_service import SLAService, sla_service

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"DELIVERED", "RETURNED", "LOST_OR_DAMAGED"}


class AtRiskService:
    """Service to evaluate and flag at-risk orders according to business rule RN-04.

    RN-04 Conditions:
    1. Fewer than 24 business hours remain before the SLA deadline and the order is NOT out for delivery.
    2. An EXCEPTION issue has been open for more than 12 hours.
    """

    def __init__(
        self,
        sla_svc: SLAService | None = None,
        holiday_svc: HolidayService | None = None,
    ) -> None:
        self.sla_service = sla_svc or sla_service
        self.holiday_service = holiday_svc or holiday_service

    async def calculate_business_hours_remaining(
        self,
        current_dt: datetime,
        deadline_dt: datetime,
        country_code: str,
    ) -> float:
        """Calculate the remaining business hours between current_dt and deadline_dt.

        Only hours falling on business days (Mon-Sat, excluding Sundays and
        destination public holidays) are counted.
        """
        if current_dt >= deadline_dt:
            return 0.0

        # Ensure UTC timezone awareness
        curr_utc = current_dt if current_dt.tzinfo is not None else current_dt.replace(tzinfo=UTC)
        dead_utc = (
            deadline_dt if deadline_dt.tzinfo is not None else deadline_dt.replace(tzinfo=UTC)
        )

        total_seconds = 0.0
        curr_date = curr_utc.date()
        end_date = dead_utc.date()

        day = curr_date
        while day <= end_date:
            if await self.sla_service.is_business_day(day, country_code):
                # Calculate window for this day in UTC
                day_start = datetime.combine(day, time.min, tzinfo=UTC)
                day_end = day_start + timedelta(days=1)

                window_start = max(curr_utc, day_start)
                window_end = min(dead_utc, day_end)

                if window_end > window_start:
                    total_seconds += (window_end - window_start).total_seconds()

            day += timedelta(days=1)

        return total_seconds / 3600.0

    async def evaluate_order_risk(
        self,
        db: AsyncSession,
        order_id: int,
        current_time: datetime | None = None,
    ) -> AtRiskEvaluationResult:
        """Evaluate RN-04 conditions for a single order without modifying persistence."""
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

        eval_dt = current_time.astimezone(UTC) if current_time else datetime.now(UTC)
        if eval_dt.tzinfo is None:
            eval_dt = eval_dt.replace(tzinfo=UTC)

        current_status = order.status.upper()
        reasons: list[str] = []
        business_hours_rem: float | None = None
        deadline_dt: datetime | None = None
        open_exception_hours: float | None = None

        # Terminal orders (DELIVERED, RETURNED, LOST_OR_DAMAGED) are never at risk
        if current_status in TERMINAL_STATUSES:
            return AtRiskEvaluationResult(
                order_id=order.order_id,
                is_at_risk=False,
                at_risk_reasons=[],
                current_status=current_status,
                business_hours_remaining=None,
                sla_deadline_datetime=None,
                open_exception_duration_hours=None,
                evaluated_at=eval_dt,
            )

        # -------------------------------------------------------------
        # Condition 1: Fewer than 24 business hours remaining and not OUT_FOR_DELIVERY
        # -------------------------------------------------------------
        is_out_for_delivery = current_status == "OUT_FOR_DELIVERY" or (
            len(order.shipping_labels) > 0
            and all(label.status.upper() == "OUT_FOR_DELIVERY" for label in order.shipping_labels)
        )

        try:
            sla_res = await self.sla_service.calculate_order_sla(db, order.order_id)
            deadline_dt = sla_res.deadline_datetime
            business_hours_rem = await self.calculate_business_hours_remaining(
                eval_dt, deadline_dt, order.destination_country
            )

            if not is_out_for_delivery and business_hours_rem <= 24.0:
                reasons.append(
                    f"FEWER_THAN_24_BUSINESS_HOURS_REMAINING: {business_hours_rem:.1f}h remaining "
                    f"before deadline {sla_res.deadline_date} (status: {current_status})"
                )
        except Exception as exc:
            logger.warning("Could not compute SLA deadline for order #%d: %s", order.order_id, exc)

        # -------------------------------------------------------------
        # Condition 2: Unresolved exception open for more than 12 hours
        # -------------------------------------------------------------
        has_open_exception = current_status == "EXCEPTION" or any(
            label.status.upper() == "EXCEPTION" for label in order.shipping_labels
        )

        if has_open_exception:
            exception_started_at: datetime | None = None
            label_ids = [lbl.label_id for lbl in order.shipping_labels]

            if label_ids:
                # Query tracking events history to find when exception started
                event_stmt = (
                    select(TrackingEvent)
                    .where(
                        TrackingEvent.label_id.in_(label_ids),
                        TrackingEvent.canonical_status == "EXCEPTION",
                    )
                    .order_by(TrackingEvent.event_timestamp.asc())
                )
                event_res = await db.execute(event_stmt)
                first_exception_event = event_res.scalars().first()
                if first_exception_event:
                    exception_started_at = first_exception_event.event_timestamp

            # Fallback to label or order creation timestamp if no event row found
            if not exception_started_at:
                for lbl in order.shipping_labels:
                    if lbl.status.upper() == "EXCEPTION":
                        exception_started_at = lbl.created_at
                        break
            if not exception_started_at:
                exception_started_at = order.created_at

            if exception_started_at.tzinfo is None:
                exception_started_at = exception_started_at.replace(tzinfo=UTC)
            else:
                exception_started_at = exception_started_at.astimezone(UTC)

            open_exception_hours = (eval_dt - exception_started_at).total_seconds() / 3600.0

            if open_exception_hours > 12.0:
                reasons.append(
                    f"UNRESOLVED_EXCEPTION_EXCEEDED_12_HOURS: Exception open for "
                    f"{open_exception_hours:.1f}h (> 12h threshold)"
                )

        is_at_risk = len(reasons) > 0

        return AtRiskEvaluationResult(
            order_id=order.order_id,
            is_at_risk=is_at_risk,
            at_risk_reasons=reasons,
            current_status=current_status,
            business_hours_remaining=business_hours_rem,
            sla_deadline_datetime=deadline_dt,
            open_exception_duration_hours=open_exception_hours,
            evaluated_at=eval_dt,
        )

    async def evaluate_and_update_order_risk(
        self,
        db: AsyncSession,
        order_id: int,
        current_time: datetime | None = None,
    ) -> AtRiskEvaluationResult:
        """Evaluate RN-04 and persist risk flags directly on the order record."""
        result = await self.evaluate_order_risk(db, order_id, current_time)

        order = await db.get(Order, order_id)
        if order is not None:
            order.is_at_risk = result.is_at_risk
            order.at_risk_reason = (
                " | ".join(result.at_risk_reasons) if result.at_risk_reasons else None
            )
            order.at_risk_evaluated_at = result.evaluated_at
            db.add(order)
            await db.commit()
            await db.refresh(order)

        return result

    async def evaluate_all_active_orders(
        self,
        db: AsyncSession,
        current_time: datetime | None = None,
    ) -> list[AtRiskEvaluationResult]:
        """Evaluate RN-04 across all active non-terminal orders."""
        stmt = (
            select(Order.order_id)
            .where(Order.status.not_in(TERMINAL_STATUSES))
            .order_by(Order.order_id.asc())
        )
        res = await db.execute(stmt)
        active_order_ids = res.scalars().all()

        results: list[AtRiskEvaluationResult] = []
        for o_id in active_order_ids:
            eval_res = await self.evaluate_and_update_order_risk(db, o_id, current_time)
            results.append(eval_res)

        return results


at_risk_service = AtRiskService()
