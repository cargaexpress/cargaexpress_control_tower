import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.carrier import Carrier
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.models.tracking_anomaly import TrackingAnomaly
from app.services.exceptions import EntityNotFoundError
from app.services.state_mapping_cache import state_mapping_cache

logger = logging.getLogger("cargaexpress.normalization")

# Business rule RN-02: Terminal states cannot be replaced
TERMINAL_STATUSES: set[str] = {
    "DELIVERED",
    "RETURNED",
    "LOST_OR_DAMAGED",
}


@dataclass(slots=True)
class NormalizationResult:
    """Result of normalizing an inbound carrier tracking event."""

    success: bool
    carrier_id: int
    tracking_number: str
    raw_status: str
    canonical_status: str | None
    previous_status: str | None
    new_status: str | None
    is_anomaly: bool
    anomaly_reason: str | None = None
    message: str = ""


async def find_carrier_by_slug_or_id(db: AsyncSession, identifier: str | int) -> Carrier | None:
    """Locate a carrier by its numeric ID, exact name, or slug substring."""
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        return await db.get(Carrier, int(identifier))

    slug = str(identifier).strip().lower()

    # Exact match (case insensitive)
    stmt = select(Carrier).where(func.lower(Carrier.name) == slug)
    carrier = (await db.execute(stmt)).scalar_one_or_none()
    if carrier is not None:
        return carrier

    # Substring match (e.g. "alpha" matches "SimCarrier Alpha")
    stmt = select(Carrier).where(func.lower(Carrier.name).like(f"%{slug}%"))
    return (await db.execute(stmt)).scalars().first()


async def normalize_and_apply_event(
    db: AsyncSession,
    carrier_identifier: str | int,
    tracking_number: str,
    raw_status: str,
    occurred_at: datetime | None = None,
    event_id: str | None = None,
    location: str | None = None,
) -> NormalizationResult:
    """Translate raw tracking event into canonical status and update shipping label.

    Enforces business rules:
    - RN-01: Translates raw_status to canonical_status using the configurable mapping cache.
    - RN-02: Protects terminal statuses (DELIVERED, RETURNED, LOST_OR_DAMAGED). If a non-terminal
      event arrives for an already terminated label, the status is NOT modified and an anomaly
      is recorded in tracking_anomalies table.
    - RN-07: Propagates status to parent Order when applicable (all labels delivered -> order delivered).
    """
    clean_tracking = tracking_number.strip()
    clean_raw_status = raw_status.strip()

    # 1. Resolve carrier
    carrier = await find_carrier_by_slug_or_id(db, carrier_identifier)
    if carrier is None:
        raise EntityNotFoundError("carrier", carrier_identifier)

    carrier_id = carrier.carrier_id

    # 2. Translate status to canonical catalog (RN-01 using in-memory cache)
    canonical_status = await state_mapping_cache.translate(carrier_id, clean_raw_status)
    if canonical_status is None:
        logger.warning(
            "Unmapped status %r for carrier %s (id=%d)",
            clean_raw_status,
            carrier.name,
            carrier_id,
        )
        canonical_status = "EXCEPTION"

    canonical_status = canonical_status.upper()

    # 3. Look up shipping label
    stmt = select(ShippingLabel).where(ShippingLabel.tracking_number == clean_tracking)
    label = (await db.execute(stmt)).scalar_one_or_none()

    if label is None:
        # Tracking number reported by carrier does not exist in WMS (Defect section 5.3)
        anomaly = TrackingAnomaly(
            carrier_id=carrier_id,
            tracking_number=clean_tracking,
            label_id=None,
            current_status="NON_EXISTENT",
            attempted_status=canonical_status,
            raw_status=clean_raw_status,
            anomaly_type="UNKNOWN_TRACKING_NUMBER",
            details=f"Received event {clean_raw_status!r} for tracking number {clean_tracking} not found in WMS.",
        )
        db.add(anomaly)
        await db.commit()
        return NormalizationResult(
            success=False,
            carrier_id=carrier_id,
            tracking_number=clean_tracking,
            raw_status=clean_raw_status,
            canonical_status=canonical_status,
            previous_status=None,
            new_status=None,
            is_anomaly=True,
            anomaly_reason="UNKNOWN_TRACKING_NUMBER",
            message=f"Shipping label {clean_tracking} not found in WMS; anomaly recorded.",
        )

    current_status = label.status.upper()

    # 4. Rule RN-02: A terminal state cannot be replaced by a non-terminal state
    if current_status in TERMINAL_STATUSES:
        if canonical_status != current_status:
            logger.info(
                "RN-02 triggered: Attempt to change terminal status %s to %s on label %s",
                current_status,
                canonical_status,
                clean_tracking,
            )
            anomaly = TrackingAnomaly(
                carrier_id=carrier_id,
                tracking_number=clean_tracking,
                label_id=label.label_id,
                current_status=current_status,
                attempted_status=canonical_status,
                raw_status=clean_raw_status,
                anomaly_type="TERMINAL_STATE_REVERSION",
                details=(
                    f"Received event {clean_raw_status!r} (canonical {canonical_status!r}) "
                    f"for label already in terminal status {current_status!r}."
                ),
            )
            db.add(anomaly)
            await db.commit()

            return NormalizationResult(
                success=True,
                carrier_id=carrier_id,
                tracking_number=clean_tracking,
                raw_status=clean_raw_status,
                canonical_status=canonical_status,
                previous_status=current_status,
                new_status=current_status,  # Preservado intacto
                is_anomaly=True,
                anomaly_reason="RN-02: Final status cannot be reverted; anomaly recorded.",
                message="Event processed: terminal status preserved and anomaly recorded.",
            )

        # If already in target terminal state (idempotent), not an anomaly
        return NormalizationResult(
            success=True,
            carrier_id=carrier_id,
            tracking_number=clean_tracking,
            raw_status=clean_raw_status,
            canonical_status=canonical_status,
            previous_status=current_status,
            new_status=current_status,
            is_anomaly=False,
            message="Status already at target terminal state.",
        )

    # 5. Apply standard status transition to shipping label
    label.status = canonical_status

    # 6. Propagar a la orden si corresponde
    order = await db.get(Order, label.order_id)
    if order is not None:
        if canonical_status in ("IN_TRANSIT", "OUT_FOR_DELIVERY"):
            if order.status.upper() in ("CREATED", "PICKED_UP", "IN_TRANSIT"):
                order.status = canonical_status
        elif canonical_status == "DELIVERED":
            # RN-07: Order meets SLA only if all of its shipping labels are delivered on time
            labels_stmt = select(ShippingLabel).where(ShippingLabel.order_id == order.order_id)
            all_labels = (await db.execute(labels_stmt)).scalars().all()
            if all(
                (item_label.status.upper() == "DELIVERED" or item_label.label_id == label.label_id)
                for item_label in all_labels
            ):
                order.status = "DELIVERED"

    await db.commit()
    await db.refresh(label)

    return NormalizationResult(
        success=True,
        carrier_id=carrier_id,
        tracking_number=clean_tracking,
        raw_status=clean_raw_status,
        canonical_status=canonical_status,
        previous_status=current_status,
        new_status=canonical_status,
        is_anomaly=False,
        message="Status normalized and updated successfully.",
    )
