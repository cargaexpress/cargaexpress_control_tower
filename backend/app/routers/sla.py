import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import ShipmentSlaTracking
from app.schemas.sla import SlaCalculationResult, SlaTrackingResponse
from app.security import require_api_key
from app.services.sla_engine import SlaEngineService

logger = logging.getLogger("cargaexpress.sla_router")

router = APIRouter(prefix="/api/v1/sla", tags=["sla & compliance"])


@router.get("/orders/{order_id}", response_model=SlaTrackingResponse)
async def get_order_sla_tracking(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> SlaTrackingResponse:
    """Get SLA calculation, delivery deadlines, and compliance status for an order (RN-03, RN-07)."""
    stmt = (
        select(Order)
        .options(
            selectinload(Order.shipping_labels).selectinload(ShippingLabel.dispatch),
            selectinload(Order.shipping_labels).selectinload(ShippingLabel.sla_tracking),
            selectinload(Order.distribution_center),
        )
        .where(Order.order_id == order_id)
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    service = SlaEngineService()
    labels_evaluations: list[SlaCalculationResult] = []
    overall_compliant = True
    overall_at_risk = False

    for label in order.shipping_labels:
        eval_res = await service.evaluate_shipment_sla(db, label)
        labels_evaluations.append(eval_res)

        if eval_res.sla_status == "BREACHED":
            overall_compliant = False
        if eval_res.is_at_risk:
            overall_at_risk = True

    return SlaTrackingResponse(
        order_id=order.order_id,
        brand_order_ref=order.brand_order_ref,
        destination_country=order.destination_country,
        shipment_type_code=order.shipment_type_code,
        labels_sla=labels_evaluations,
        overall_order_compliant=overall_compliant,
        overall_at_risk=overall_at_risk,
    )


@router.get("/at-risk", response_model=list[SlaCalculationResult])
async def list_at_risk_shipments(
    country_code: str | None = Query(default=None, description="Filter by destination country code"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> list[SlaCalculationResult]:
    """Retrieve all shipments currently classified as at risk of breaching SLA (RN-04)."""
    stmt = select(ShipmentSlaTracking).where(ShipmentSlaTracking.is_at_risk.is_(True))
    if country_code:
        stmt = stmt.where(ShipmentSlaTracking.destination_country == country_code.strip().upper())

    stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    records = res.scalars().all()

    return [
        SlaCalculationResult(
            tracking_number=r.tracking_number,
            destination_country=r.destination_country,
            shipment_type_code=r.shipment_type_code,
            sla_business_days=r.sla_business_days,
            dispatched_at=r.dispatched_at,
            sla_start_date=r.sla_start_date,
            deadline_utc=r.deadline_utc,
            delivered_at=r.delivered_at,
            is_at_risk=r.is_at_risk,
            risk_reason=r.risk_reason,
            business_hours_remaining=r.business_hours_remaining,
            exception_open_duration_hours=r.exception_open_duration_hours,
            sla_status=r.sla_status,
            responsible_party=r.responsible_party,
        )
        for r in records
    ]
