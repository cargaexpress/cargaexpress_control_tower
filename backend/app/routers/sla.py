import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.financial import FreightPenalty
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import ShipmentSlaTracking
from app.schemas.sla import (
    BrandSlaMetricsResponse,
    CarrierSlaMetricsResponse,
    HistoricalSlaItem,
    HistoricalSlaResponse,
    PaginatedShipmentsSlaResponse,
    ShipmentSlaSummaryItem,
    SlaCalculationResult,
    SlaTrackingResponse,
)
from app.security import get_current_brand, get_current_carrier, require_api_key
from app.services.sla_engine import SlaEngineService

logger = logging.getLogger("cargaexpress.sla_router")

router = APIRouter(prefix="/api/v1/sla", tags=["Operational: SLA & Compliance", "sla & compliance"])


# =============================================================================
# 1. Existing Order SLA Tracking & At-Risk Endpoints
# =============================================================================


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
    country_code: str | None = Query(
        default=None, description="Filter by destination country code"
    ),
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


# =============================================================================
# 2. Work Package 1: Brand Queries (Volume, Compliance, Breaches, Penalties)
# =============================================================================


@router.get("/brand/metrics", response_model=BrandSlaMetricsResponse)
async def get_brand_sla_metrics(
    start_date: date | None = Query(default=None, description="Filter from creation date"),
    end_date: date | None = Query(default=None, description="Filter to creation date"),
    carrier_id: int | None = Query(default=None, description="Optional carrier ID filter"),
    db: AsyncSession = Depends(get_db),
    brand_id: int = Depends(get_current_brand),
) -> BrandSlaMetricsResponse:
    """Consult aggregated SLA compliance, shipment volume, breaches, and penalties for the authenticated brand."""
    stmt = (
        select(ShippingLabel)
        .join(Order, ShippingLabel.order_id == Order.order_id)
        .options(selectinload(ShippingLabel.sla_tracking))
        .where(Order.brand_id == brand_id)
    )
    if carrier_id:
        stmt = stmt.where(ShippingLabel.carrier_id == carrier_id)
    if start_date:
        stmt = stmt.where(func.date(Order.created_at) >= start_date)
    if end_date:
        stmt = stmt.where(func.date(Order.created_at) <= end_date)

    res = await db.execute(stmt)
    labels = res.scalars().all()

    total_shipments = len(labels)
    delivered_shipments = sum(1 for lbl in labels if (lbl.status or "").upper() == "DELIVERED")
    compliant_shipments = sum(
        1
        for lbl in labels
        if lbl.sla_tracking and (lbl.sla_tracking.sla_status or "").upper() in {"MET", "COMPLIANT"}
    )
    breached_shipments = sum(
        1
        for lbl in labels
        if lbl.sla_tracking and (lbl.sla_tracking.sla_status or "").upper() in {"BREACHED", "LATE"}
    )
    at_risk_shipments = sum(1 for lbl in labels if lbl.sla_tracking and lbl.sla_tracking.is_at_risk)
    delayed_shipments = breached_shipments

    compliance_rate = Decimal("100.00")
    if total_shipments > 0:
        compliance_rate = (
            (Decimal(compliant_shipments) / Decimal(total_shipments)) * Decimal("100.00")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Penalties for this brand
    stmt_penalties = select(FreightPenalty).where(FreightPenalty.brand_id == brand_id)
    if carrier_id:
        stmt_penalties = stmt_penalties.where(FreightPenalty.carrier_id == carrier_id)
    if start_date:
        stmt_penalties = stmt_penalties.where(func.date(FreightPenalty.calculated_at) >= start_date)
    if end_date:
        stmt_penalties = stmt_penalties.where(func.date(FreightPenalty.calculated_at) <= end_date)

    res_pen = await db.execute(stmt_penalties)
    penalties = res_pen.scalars().all()

    total_penalties = sum(
        (p.penalty_amount for p in penalties if p.penalty_amount is not None), Decimal("0.00")
    )
    approved_penalties = sum(
        (
            p.penalty_amount
            for p in penalties
            if p.calculation_status == "APPROVED" and p.penalty_amount is not None
        ),
        Decimal("0.00"),
    )
    pending_penalties_count = sum(
        1 for p in penalties if p.calculation_status == "PENDING_APPROVAL"
    )

    brand = await db.get(Brand, brand_id)

    return BrandSlaMetricsResponse(
        brand_id=brand_id,
        brand_name=brand.name if brand else None,
        total_shipments=total_shipments,
        delivered_shipments=delivered_shipments,
        compliant_shipments=compliant_shipments,
        breached_shipments=breached_shipments,
        at_risk_shipments=at_risk_shipments,
        delayed_shipments=delayed_shipments,
        compliance_rate_pct=compliance_rate,
        total_penalties_amount=total_penalties,
        approved_penalties_amount=approved_penalties,
        pending_penalties_count=pending_penalties_count,
    )


@router.get("/brand/shipments", response_model=PaginatedShipmentsSlaResponse)
async def list_brand_shipments_sla(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    carrier_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    sla_status: str | None = Query(default=None, description="MET, BREACHED, PENDING"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    brand_id: int = Depends(get_current_brand),
) -> PaginatedShipmentsSlaResponse:
    """Consult detailed paginated shipment SLA compliance, tracking history, and penalties for the authenticated brand."""
    stmt = (
        select(ShippingLabel)
        .join(Order, ShippingLabel.order_id == Order.order_id)
        .options(
            selectinload(ShippingLabel.order),
            selectinload(ShippingLabel.carrier),
            selectinload(ShippingLabel.sla_tracking),
        )
        .where(Order.brand_id == brand_id)
    )
    if carrier_id:
        stmt = stmt.where(ShippingLabel.carrier_id == carrier_id)
    if status_filter:
        stmt = stmt.where(ShippingLabel.status == status_filter.strip().upper())
    if start_date:
        stmt = stmt.where(func.date(Order.created_at) >= start_date)
    if end_date:
        stmt = stmt.where(func.date(Order.created_at) <= end_date)

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total_count = total_res.scalar_one()

    # Paginate
    stmt = stmt.order_by(ShippingLabel.label_id.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    labels = res.scalars().all()

    items: list[ShipmentSlaSummaryItem] = []
    for label in labels:
        # Check associated penalty
        stmt_p = select(FreightPenalty).where(FreightPenalty.label_id == label.label_id)
        res_p = await db.execute(stmt_p)
        penalty = res_p.scalar_one_or_none()

        sla_rec = label.sla_tracking
        items.append(
            ShipmentSlaSummaryItem(
                label_id=label.label_id,
                order_id=label.order_id,
                tracking_number=label.tracking_number,
                brand_id=brand_id,
                carrier_id=label.carrier_id,
                carrier_name=label.carrier.name if label.carrier else None,
                brand_order_ref=label.order.brand_order_ref if label.order else None,
                status=label.status,
                dispatched_at=sla_rec.dispatched_at if sla_rec else None,
                deadline_utc=sla_rec.deadline_utc if sla_rec else None,
                delivered_at=sla_rec.delivered_at if sla_rec else None,
                sla_status=sla_rec.sla_status if sla_rec else "PENDING",
                is_at_risk=sla_rec.is_at_risk if sla_rec else False,
                delay_business_days=penalty.delay_business_days if penalty else 0,
                delay_level=penalty.delay_level if penalty else "NO_DELAY",
                responsible_party=penalty.responsible_party
                if penalty
                else (sla_rec.responsible_party if sla_rec else None),
                penalty_amount=penalty.penalty_amount if penalty else None,
                calculation_status=penalty.calculation_status if penalty else None,
                is_carrier_payable=penalty.is_carrier_payable if penalty else False,
            )
        )

    return PaginatedShipmentsSlaResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get("/brand/history", response_model=HistoricalSlaResponse)
async def get_brand_sla_history(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    brand_id: int = Depends(get_current_brand),
) -> HistoricalSlaResponse:
    """Consult daily historical SLA compliance and penalty trends for the authenticated brand."""
    now_date = date.today()
    s_date = start_date or (now_date - timedelta(days=30))
    e_date = end_date or now_date

    stmt = (
        select(
            func.date(Order.created_at).label("day"),
            func.count(ShippingLabel.label_id).label("total_shipments"),
            func.sum(
                case((ShipmentSlaTracking.sla_status.in_(["MET", "COMPLIANT"]), 1), else_=0)
            ).label("compliant_shipments"),
            func.sum(
                case((ShipmentSlaTracking.sla_status.in_(["BREACHED", "LATE"]), 1), else_=0)
            ).label("breached_shipments"),
        )
        .join(Order, ShippingLabel.order_id == Order.order_id)
        .outerjoin(ShipmentSlaTracking, ShippingLabel.label_id == ShipmentSlaTracking.label_id)
        .where(
            Order.brand_id == brand_id,
            func.date(Order.created_at) >= s_date,
            func.date(Order.created_at) <= e_date,
        )
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at).asc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    periods: list[HistoricalSlaItem] = []
    for r in rows:
        d = r.day if isinstance(r.day, date) else date.fromisoformat(str(r.day))
        total = int(r.total_shipments or 0)
        compliant = int(r.compliant_shipments or 0)
        breached = int(r.breached_shipments or 0)
        rate = Decimal("100.00")
        if total > 0:
            rate = ((Decimal(compliant) / Decimal(total)) * Decimal("100.00")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        # Penalties for that day
        stmt_p = select(func.sum(FreightPenalty.penalty_amount)).where(
            FreightPenalty.brand_id == brand_id,
            func.date(FreightPenalty.calculated_at) == d,
            FreightPenalty.penalty_amount.is_not(None),
        )
        res_p = await db.execute(stmt_p)
        pen_sum = res_p.scalar_one_or_none() or Decimal("0.00")

        periods.append(
            HistoricalSlaItem(
                period_date=d,
                total_shipments=total,
                compliant_shipments=compliant,
                breached_shipments=breached,
                compliance_rate_pct=rate,
                total_penalties_amount=Decimal(str(pen_sum)),
            )
        )

    return HistoricalSlaResponse(periods=periods)


# =============================================================================
# 3. Work Package 1: Carrier Queries (Assigned Volume, Compliance, Penalties)
# =============================================================================


@router.get("/carrier/metrics", response_model=CarrierSlaMetricsResponse)
async def get_carrier_sla_metrics(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    brand_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    carrier_id: int = Depends(get_current_carrier),
) -> CarrierSlaMetricsResponse:
    """Consult assigned shipment volume, SLA compliance, breaches, and attributable penalties for the carrier."""
    stmt = (
        select(ShippingLabel)
        .join(Order, ShippingLabel.order_id == Order.order_id)
        .options(selectinload(ShippingLabel.sla_tracking))
        .where(ShippingLabel.carrier_id == carrier_id)
    )
    if brand_id:
        stmt = stmt.where(Order.brand_id == brand_id)
    if start_date:
        stmt = stmt.where(func.date(Order.created_at) >= start_date)
    if end_date:
        stmt = stmt.where(func.date(Order.created_at) <= end_date)

    res = await db.execute(stmt)
    labels = res.scalars().all()

    total_shipments = len(labels)
    delivered_shipments = sum(1 for lbl in labels if (lbl.status or "").upper() == "DELIVERED")
    compliant_shipments = sum(
        1
        for lbl in labels
        if lbl.sla_tracking and (lbl.sla_tracking.sla_status or "").upper() in {"MET", "COMPLIANT"}
    )
    breached_shipments = sum(
        1
        for lbl in labels
        if lbl.sla_tracking and (lbl.sla_tracking.sla_status or "").upper() in {"BREACHED", "LATE"}
    )
    at_risk_shipments = sum(1 for lbl in labels if lbl.sla_tracking and lbl.sla_tracking.is_at_risk)
    delayed_shipments = breached_shipments

    compliance_rate = Decimal("100.00")
    if total_shipments > 0:
        compliance_rate = (
            (Decimal(compliant_shipments) / Decimal(total_shipments)) * Decimal("100.00")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Recoverable penalties payable by this carrier
    stmt_penalties = select(FreightPenalty).where(
        FreightPenalty.carrier_id == carrier_id,
        FreightPenalty.is_carrier_payable.is_(True),
    )
    if brand_id:
        stmt_penalties = stmt_penalties.where(FreightPenalty.brand_id == brand_id)
    if start_date:
        stmt_penalties = stmt_penalties.where(func.date(FreightPenalty.calculated_at) >= start_date)
    if end_date:
        stmt_penalties = stmt_penalties.where(func.date(FreightPenalty.calculated_at) <= end_date)

    res_pen = await db.execute(stmt_penalties)
    penalties = res_pen.scalars().all()

    carrier_payable_penalties = sum(
        (p.penalty_amount for p in penalties if p.penalty_amount is not None), Decimal("0.00")
    )
    pending_penalties_count = sum(
        1 for p in penalties if p.calculation_status == "PENDING_APPROVAL"
    )

    carrier = await db.get(Carrier, carrier_id)

    return CarrierSlaMetricsResponse(
        carrier_id=carrier_id,
        carrier_name=carrier.name if carrier else None,
        total_shipments=total_shipments,
        delivered_shipments=delivered_shipments,
        compliant_shipments=compliant_shipments,
        breached_shipments=breached_shipments,
        at_risk_shipments=at_risk_shipments,
        delayed_shipments=delayed_shipments,
        compliance_rate_pct=compliance_rate,
        carrier_payable_penalties_amount=carrier_payable_penalties,
        pending_penalties_count=pending_penalties_count,
    )


@router.get("/carrier/shipments", response_model=PaginatedShipmentsSlaResponse)
async def list_carrier_shipments_sla(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    brand_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    carrier_id: int = Depends(get_current_carrier),
) -> PaginatedShipmentsSlaResponse:
    """Consult detailed paginated assigned shipments, SLA status, and attributable penalties for the carrier."""
    stmt = (
        select(ShippingLabel)
        .join(Order, ShippingLabel.order_id == Order.order_id)
        .options(
            selectinload(ShippingLabel.order),
            selectinload(ShippingLabel.carrier),
            selectinload(ShippingLabel.sla_tracking),
        )
        .where(ShippingLabel.carrier_id == carrier_id)
    )
    if brand_id:
        stmt = stmt.where(Order.brand_id == brand_id)
    if status_filter:
        stmt = stmt.where(ShippingLabel.status == status_filter.strip().upper())
    if start_date:
        stmt = stmt.where(func.date(Order.created_at) >= start_date)
    if end_date:
        stmt = stmt.where(func.date(Order.created_at) <= end_date)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total_count = total_res.scalar_one()

    stmt = stmt.order_by(ShippingLabel.label_id.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    labels = res.scalars().all()

    items: list[ShipmentSlaSummaryItem] = []
    for label in labels:
        stmt_p = select(FreightPenalty).where(FreightPenalty.label_id == label.label_id)
        res_p = await db.execute(stmt_p)
        penalty = res_p.scalar_one_or_none()

        sla_rec = label.sla_tracking
        items.append(
            ShipmentSlaSummaryItem(
                label_id=label.label_id,
                order_id=label.order_id,
                tracking_number=label.tracking_number,
                brand_id=label.order.brand_id if label.order else 0,
                carrier_id=carrier_id,
                carrier_name=label.carrier.name if label.carrier else None,
                brand_order_ref=label.order.brand_order_ref if label.order else None,
                status=label.status,
                dispatched_at=sla_rec.dispatched_at if sla_rec else None,
                deadline_utc=sla_rec.deadline_utc if sla_rec else None,
                delivered_at=sla_rec.delivered_at if sla_rec else None,
                sla_status=sla_rec.sla_status if sla_rec else "PENDING",
                is_at_risk=sla_rec.is_at_risk if sla_rec else False,
                delay_business_days=penalty.delay_business_days if penalty else 0,
                delay_level=penalty.delay_level if penalty else "NO_DELAY",
                responsible_party=penalty.responsible_party
                if penalty
                else (sla_rec.responsible_party if sla_rec else None),
                penalty_amount=penalty.penalty_amount if penalty else None,
                calculation_status=penalty.calculation_status if penalty else None,
                is_carrier_payable=penalty.is_carrier_payable if penalty else False,
            )
        )

    return PaginatedShipmentsSlaResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get("/carrier/history", response_model=HistoricalSlaResponse)
async def get_carrier_sla_history(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    carrier_id: int = Depends(get_current_carrier),
) -> HistoricalSlaResponse:
    """Consult daily historical SLA compliance and carrier-attributable penalty trends for the carrier."""
    now_date = date.today()
    s_date = start_date or (now_date - timedelta(days=30))
    e_date = end_date or now_date

    stmt = (
        select(
            func.date(Order.created_at).label("day"),
            func.count(ShippingLabel.label_id).label("total_shipments"),
            func.sum(
                case((ShipmentSlaTracking.sla_status.in_(["MET", "COMPLIANT"]), 1), else_=0)
            ).label("compliant_shipments"),
            func.sum(
                case((ShipmentSlaTracking.sla_status.in_(["BREACHED", "LATE"]), 1), else_=0)
            ).label("breached_shipments"),
        )
        .join(Order, ShippingLabel.order_id == Order.order_id)
        .outerjoin(ShipmentSlaTracking, ShippingLabel.label_id == ShipmentSlaTracking.label_id)
        .where(
            ShippingLabel.carrier_id == carrier_id,
            func.date(Order.created_at) >= s_date,
            func.date(Order.created_at) <= e_date,
        )
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at).asc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    periods: list[HistoricalSlaItem] = []
    for r in rows:
        d = r.day if isinstance(r.day, date) else date.fromisoformat(str(r.day))
        total = int(r.total_shipments or 0)
        compliant = int(r.compliant_shipments or 0)
        breached = int(r.breached_shipments or 0)
        rate = Decimal("100.00")
        if total > 0:
            rate = ((Decimal(compliant) / Decimal(total)) * Decimal("100.00")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        stmt_p = select(func.sum(FreightPenalty.penalty_amount)).where(
            FreightPenalty.carrier_id == carrier_id,
            FreightPenalty.is_carrier_payable.is_(True),
            func.date(FreightPenalty.calculated_at) == d,
            FreightPenalty.penalty_amount.is_not(None),
        )
        res_p = await db.execute(stmt_p)
        pen_sum = res_p.scalar_one_or_none() or Decimal("0.00")

        periods.append(
            HistoricalSlaItem(
                period_date=d,
                total_shipments=total,
                compliant_shipments=compliant,
                breached_shipments=breached,
                compliance_rate_pct=rate,
                total_penalties_amount=Decimal(str(pen_sum)),
            )
        )

    return HistoricalSlaResponse(periods=periods)
