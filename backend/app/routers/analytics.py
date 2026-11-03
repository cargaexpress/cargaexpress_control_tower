import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analytics import (
    EtlBatchRun,
    FactFinancialPenalty,
    FactShipmentSla,
)
from app.schemas.analytics import (
    AnalyticsKpiSummary,
    EtlBatchRunRead,
    FactFinancialPenaltyRead,
    FactShipmentSlaRead,
)
from app.security import require_admin, require_api_key, require_internal_service
from app.services.analytical_etl import AnalyticalEtlService

logger = logging.getLogger("cargaexpress.analytics_router")

router = APIRouter(
    prefix="/api/v1/analytics", tags=["Operational: Analytics", "analytics & data warehouse"]
)


@router.post(
    "/etl/run",
    response_model=EtlBatchRunRead,
    tags=["Internal Processes: Analytics ETL"],
    summary="Execute the full analytical ETL/ELT pipeline (Internal process)",
)
async def trigger_etl_run(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_internal_service),
) -> EtlBatchRunRead:
    """Execute the full analytical ETL/ELT pipeline (Admin only).

    Extracts operational data from WMS orders, dispatches, tracking events,
    and financial calculations, transforms them into dimensional star schema,
    and logs data lineage.
    """
    service = AnalyticalEtlService()
    batch = await service.run_etl_pipeline(db)
    await db.commit()
    await db.refresh(batch)
    return EtlBatchRunRead.model_validate(batch)


@router.get("/etl/batches", response_model=list[EtlBatchRunRead])
async def list_etl_batches(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[EtlBatchRunRead]:
    """Audit ETL executions and data lineage tracking (Admin only)."""
    stmt = select(EtlBatchRun).order_by(EtlBatchRun.batch_id.desc()).limit(limit)
    res = await db.execute(stmt)
    batches = res.scalars().all()
    return [EtlBatchRunRead.model_validate(b) for b in batches]


@router.get("/facts/shipments-sla", response_model=list[FactShipmentSlaRead])
async def query_fact_shipments_sla(
    brand_key: int | None = Query(default=None),
    carrier_key: int | None = Query(default=None),
    sla_status: str | None = Query(default=None),
    is_breached: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> list[FactShipmentSlaRead]:
    """Query analytical fact table for shipment SLA performance."""
    stmt = select(FactShipmentSla)
    if brand_key:
        stmt = stmt.where(FactShipmentSla.brand_key == brand_key)
    if carrier_key:
        stmt = stmt.where(FactShipmentSla.carrier_key == carrier_key)
    if sla_status:
        stmt = stmt.where(FactShipmentSla.sla_status == sla_status.strip().upper())
    if is_breached is not None:
        stmt = stmt.where(FactShipmentSla.is_sla_breached.is_(is_breached))

    stmt = stmt.order_by(FactShipmentSla.fact_sla_id.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    facts = res.scalars().all()
    return [FactShipmentSlaRead.model_validate(f) for f in facts]


@router.get("/facts/penalties", response_model=list[FactFinancialPenaltyRead])
async def query_fact_penalties(
    brand_key: int | None = Query(default=None),
    carrier_key: int | None = Query(default=None),
    delay_level: str | None = Query(default=None),
    is_carrier_payable: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> list[FactFinancialPenaltyRead]:
    """Query analytical fact table for financial penalties."""
    stmt = select(FactFinancialPenalty)
    if brand_key:
        stmt = stmt.where(FactFinancialPenalty.brand_key == brand_key)
    if carrier_key:
        stmt = stmt.where(FactFinancialPenalty.carrier_key == carrier_key)
    if delay_level:
        stmt = stmt.where(FactFinancialPenalty.delay_level == delay_level.strip().upper())
    if is_carrier_payable is not None:
        stmt = stmt.where(FactFinancialPenalty.is_carrier_payable.is_(is_carrier_payable))

    stmt = stmt.order_by(FactFinancialPenalty.fact_penalty_id.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    facts = res.scalars().all()
    return [FactFinancialPenaltyRead.model_validate(f) for f in facts]


@router.get("/kpis", response_model=AnalyticsKpiSummary)
async def get_analytics_kpi_summary(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> AnalyticsKpiSummary:
    """Query high-level analytical KPIs aggregated across fact tables."""
    # 1. Shipments SLA aggregates
    stmt_sla = select(
        func.count(FactShipmentSla.fact_sla_id).label("total_shipments"),
        func.sum(case((FactShipmentSla.sla_status.in_(["MET", "COMPLIANT"]), 1), else_=0)).label(
            "compliant_shipments"
        ),
        func.sum(case((FactShipmentSla.sla_status.in_(["BREACHED", "LATE"]), 1), else_=0)).label(
            "breached_shipments"
        ),
        func.sum(case((FactShipmentSla.is_at_risk.is_(True), 1), else_=0)).label(
            "at_risk_shipments"
        ),
        func.sum(FactShipmentSla.freight_amount).label("total_freight"),
    )
    res_sla = await db.execute(stmt_sla)
    row_sla = res_sla.one()

    total_shipments = int(row_sla.total_shipments or 0)
    compliant = int(row_sla.compliant_shipments or 0)
    breached = int(row_sla.breached_shipments or 0)
    at_risk = int(row_sla.at_risk_shipments or 0)
    total_freight = Decimal(str(row_sla.total_freight or 0.00))

    compliance_rate = Decimal("100.00")
    if total_shipments > 0:
        compliance_rate = (
            (Decimal(compliant) / Decimal(total_shipments)) * Decimal("100.00")
        ).quantize(Decimal("0.01"))

    # 2. Financial Penalties aggregates
    stmt_pen = select(
        func.sum(FactFinancialPenalty.penalty_amount).label("total_penalties"),
        func.sum(
            case(
                (
                    FactFinancialPenalty.is_carrier_payable.is_(True),
                    FactFinancialPenalty.penalty_amount,
                ),
                else_=Decimal("0.00"),
            )
        ).label("carrier_payable_penalties"),
    )
    res_pen = await db.execute(stmt_pen)
    row_pen = res_pen.one()

    total_penalties = Decimal(str(row_pen.total_penalties or 0.00))
    carrier_payable = Decimal(str(row_pen.carrier_payable_penalties or 0.00))

    # 3. Batches count
    stmt_b = select(func.count(EtlBatchRun.batch_id))
    res_b = await db.execute(stmt_b)
    batch_count = int(res_b.scalar_one() or 0)

    return AnalyticsKpiSummary(
        total_shipments=total_shipments,
        compliant_shipments=compliant,
        breached_shipments=breached,
        at_risk_shipments=at_risk,
        compliance_rate_pct=compliance_rate,
        total_freight_volume=total_freight,
        total_penalties_amount=total_penalties,
        total_carrier_payable_penalties=carrier_payable,
        total_etl_batches_run=batch_count,
    )
