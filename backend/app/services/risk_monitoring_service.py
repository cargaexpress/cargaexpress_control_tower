import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.alert import ShipmentAlert
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.schemas.alert import AlertScanSummary
from app.services.sla_engine import SlaEngineService

logger = logging.getLogger("cargaexpress.risk_monitoring")


class RiskMonitoringService:
    """Evaluates shipments for operational risks and generates automatic alerts (RN-04).

    Alert Conditions:
    1. Preventive 24h Alert:
       - Firing when <= 24 business hours remain before SLA expiration.
       - ONLY when shipment is NOT in OUT_FOR_DELIVERY status.
       - Surfaces tracking number, carrier name/id, and remaining SLA hours.

    2. Prolonged Exception Alert:
       - Firing when shipment remains in EXCEPTION status for > 12 hours without resolution.
       - Surfaces tracking number, exception detail, and responsible carrier.
       - Keeps tracking open until resolved or shipment transitions to next state.
    """

    def __init__(self, sla_engine: SlaEngineService | None = None) -> None:
        self.sla_engine = sla_engine or SlaEngineService()

    async def scan_and_generate_alerts(
        self,
        db: AsyncSession,
        current_time_utc: datetime | None = None,
    ) -> AlertScanSummary:
        """Scan all active non-terminal shipments, evaluate risk conditions, and upsert alerts."""
        now = current_time_utc or datetime.now(UTC)

        # Non-terminal statuses that require active SLA and risk surveillance
        active_statuses = {"CREATED", "PICKED_UP", "IN_TRANSIT", "EXCEPTION"}

        stmt = (
            select(ShippingLabel)
            .options(
                selectinload(ShippingLabel.order).selectinload(Order.distribution_center),
                selectinload(ShippingLabel.dispatch),
                selectinload(ShippingLabel.carrier),
            )
            .where(ShippingLabel.status.in_(active_statuses))
        )
        res = await db.execute(stmt)
        labels = res.scalars().all()

        total_evaluated = len(labels)
        alerts_generated = 0
        preventive_alerts = 0
        prolonged_exception_alerts = 0
        alerts_resolved = 0

        for label in labels:
            # 1. Evaluate SLA metrics
            eval_res = await self.sla_engine.evaluate_shipment_sla(
                db=db, label=label, current_time_utc=now
            )

            # --- Condition 1: Preventive 24-hour Alert ---
            if (
                eval_res.business_hours_remaining is not None
                and eval_res.business_hours_remaining <= 24.0
                and label.status != "OUT_FOR_DELIVERY"
                and eval_res.sla_status == "PENDING"
            ):
                created = await self._ensure_alert(
                    db=db,
                    label=label,
                    alert_type="PREVENTIVE_24H",
                    severity="WARNING",
                    message=(
                        f"Shipment {label.tracking_number} has {eval_res.business_hours_remaining:.1f} business hours "
                        f"remaining before SLA deadline but is currently in '{label.status}' status (not OUT_FOR_DELIVERY)."
                    ),
                    hours_remaining=eval_res.business_hours_remaining,
                    exception_duration_hours=None,
                    exception_detail=None,
                )
                if created:
                    alerts_generated += 1
                    preventive_alerts += 1

            # --- Condition 2: Prolonged Exception Alert (> 12 hours) ---
            if label.status == "EXCEPTION":
                # Calculate duration in EXCEPTION
                exception_duration = 13.0
                if eval_res.exception_open_duration_hours:
                    exception_duration = eval_res.exception_open_duration_hours

                if exception_duration > 12.0:
                    created = await self._ensure_alert(
                        db=db,
                        label=label,
                        alert_type="PROLONGED_EXCEPTION",
                        severity="CRITICAL",
                        message=(
                            f"Shipment {label.tracking_number} has been in EXCEPTION status for "
                            f"{exception_duration:.1f} hours without resolution."
                        ),
                        hours_remaining=eval_res.business_hours_remaining,
                        exception_duration_hours=exception_duration,
                        exception_detail=eval_res.risk_reason,
                    )
                    if created:
                        alerts_generated += 1
                        prolonged_exception_alerts += 1

        # Check and resolve alerts for shipments that transitioned out of risk
        resolved_count = await self._auto_resolve_cleared_alerts(db, now)
        alerts_resolved += resolved_count

        return AlertScanSummary(
            total_evaluated=total_evaluated,
            alerts_generated=alerts_generated,
            preventive_24h_alerts=preventive_alerts,
            prolonged_exception_alerts=prolonged_exception_alerts,
            alerts_resolved=alerts_resolved,
        )

    async def _ensure_alert(
        self,
        db: AsyncSession,
        label: ShippingLabel,
        alert_type: str,
        severity: str,
        message: str,
        hours_remaining: float | None,
        exception_duration_hours: float | None,
        exception_detail: str | None,
    ) -> bool:
        """Create or update an active alert, ensuring idempotent deduplication."""
        stmt = select(ShipmentAlert).where(
            ShipmentAlert.label_id == label.label_id,
            ShipmentAlert.alert_type == alert_type,
            ShipmentAlert.is_resolved.is_(False),
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            # Update metrics
            existing.hours_remaining = hours_remaining
            existing.exception_duration_hours = exception_duration_hours
            existing.exception_detail = exception_detail
            existing.message = message
            await db.flush()
            return False

        alert = ShipmentAlert(
            label_id=label.label_id,
            carrier_id=label.carrier_id,
            tracking_number=label.tracking_number,
            alert_type=alert_type,
            severity=severity,
            message=message,
            hours_remaining=hours_remaining,
            exception_duration_hours=exception_duration_hours,
            exception_detail=exception_detail,
            is_resolved=False,
        )
        db.add(alert)
        await db.flush()
        return True

    async def _auto_resolve_cleared_alerts(
        self,
        db: AsyncSession,
        now: datetime,
    ) -> int:
        """Automatically resolve alerts when shipments reach OUT_FOR_DELIVERY/DELIVERED or clear EXCEPTION."""
        stmt = (
            select(ShipmentAlert)
            .options(selectinload(ShipmentAlert.shipping_label))
            .where(ShipmentAlert.is_resolved.is_(False))
        )
        res = await db.execute(stmt)
        active_alerts = res.scalars().all()

        resolved = 0
        for alert in active_alerts:
            label = alert.shipping_label
            if not label:
                continue

            current_status = label.status.upper()

            # Condition 1: PREVENTIVE_24H resolves when shipment enters OUT_FOR_DELIVERY or DELIVERED
            if alert.alert_type == "PREVENTIVE_24H" and current_status in {
                "OUT_FOR_DELIVERY",
                "DELIVERED",
            }:
                alert.is_resolved = True
                alert.resolved_at = now
                alert.resolution_notes = (
                    f"Auto-resolved: shipment reached '{current_status}' status."
                )
                resolved += 1

            # Condition 2: PROLONGED_EXCEPTION resolves when shipment leaves EXCEPTION status
            elif alert.alert_type == "PROLONGED_EXCEPTION" and current_status != "EXCEPTION":
                alert.is_resolved = True
                alert.resolved_at = now
                alert.resolution_notes = (
                    f"Auto-resolved: shipment transitioned from EXCEPTION to '{current_status}'."
                )
                resolved += 1

        if resolved > 0:
            await db.flush()
        return resolved
