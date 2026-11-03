import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.alert import ShipmentAlert
from app.schemas.alert import AlertResolveRequest, AlertScanSummary, ShipmentAlertRead
from app.security import require_api_key
from app.services.risk_monitoring_service import RiskMonitoringService

logger = logging.getLogger("cargaexpress.alerts_router")

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts & risk monitoring"])


@router.get("", response_model=list[ShipmentAlertRead])
async def list_alerts(
    alert_type: str | None = Query(
        default=None,
        description="Filter by type: PREVENTIVE_24H or PROLONGED_EXCEPTION",
    ),
    carrier_id: int | None = Query(default=None, description="Filter by carrier ID"),
    is_resolved: bool | None = Query(
        default=False,
        description="Filter by resolution status (defaults to false for active alerts)",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> list[ShipmentAlertRead]:
    """List operational alerts for shipments at risk or with prolonged exceptions (RN-04)."""
    stmt = select(ShipmentAlert).options(selectinload(ShipmentAlert.carrier))

    if alert_type:
        stmt = stmt.where(ShipmentAlert.alert_type == alert_type.strip().upper())
    if carrier_id is not None:
        stmt = stmt.where(ShipmentAlert.carrier_id == carrier_id)
    if is_resolved is not None:
        stmt = stmt.where(ShipmentAlert.is_resolved == is_resolved)

    stmt = stmt.order_by(ShipmentAlert.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    records = res.scalars().all()

    return [
        ShipmentAlertRead(
            alert_id=r.alert_id,
            label_id=r.label_id,
            carrier_id=r.carrier_id,
            carrier_name=r.carrier.name if r.carrier else None,
            tracking_number=r.tracking_number,
            alert_type=r.alert_type,
            severity=r.severity,
            message=r.message,
            hours_remaining=r.hours_remaining,
            exception_duration_hours=r.exception_duration_hours,
            exception_detail=r.exception_detail,
            is_resolved=r.is_resolved,
            resolved_at=r.resolved_at,
            resolution_notes=r.resolution_notes,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in records
    ]


@router.post("/scan", response_model=AlertScanSummary)
async def trigger_risk_scan(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> AlertScanSummary:
    """Trigger an on-demand scan across all active shipments to identify risks and generate alerts."""
    service = RiskMonitoringService()
    summary = await service.scan_and_generate_alerts(db)
    return summary


@router.post("/{alert_id}/resolve", response_model=ShipmentAlertRead)
async def resolve_alert(
    alert_id: int,
    payload: AlertResolveRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> ShipmentAlertRead:
    """Manually mark an active alert as resolved with resolution notes."""
    stmt = (
        select(ShipmentAlert)
        .options(selectinload(ShipmentAlert.carrier))
        .where(ShipmentAlert.alert_id == alert_id)
    )
    res = await db.execute(stmt)
    alert = res.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    alert.is_resolved = True
    alert.resolved_at = datetime.now(UTC)
    alert.resolution_notes = payload.resolution_notes
    await db.commit()
    await db.refresh(alert)

    return ShipmentAlertRead(
        alert_id=alert.alert_id,
        label_id=alert.label_id,
        carrier_id=alert.carrier_id,
        carrier_name=alert.carrier.name if alert.carrier else None,
        tracking_number=alert.tracking_number,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
        hours_remaining=alert.hours_remaining,
        exception_duration_hours=alert.exception_duration_hours,
        exception_detail=alert.exception_detail,
        is_resolved=alert.is_resolved,
        resolved_at=alert.resolved_at,
        resolution_notes=alert.resolution_notes,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )
