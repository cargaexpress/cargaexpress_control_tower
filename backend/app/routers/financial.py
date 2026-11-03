import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.financial import (
    FinancialLedgerEntry,
    FinancialSettlement,
    FreightPenalty,
)
from app.models.shipping_label import ShippingLabel
from app.schemas.financial import (
    AttributionRead,
    FinancialLedgerEntryRead,
    FinancialSettlementRead,
    FreightPenaltyRead,
    SettlementGenerateRequest,
)
from app.security import get_current_brand, require_admin, require_api_key
from app.services.financial_engine import FinancialEngineService

logger = logging.getLogger("cargaexpress.financial_router")

router = APIRouter(prefix="/api/v1/financial", tags=["financial & penalties"])


# =============================================================================
# 1. Responsibility Attribution
# =============================================================================


@router.get("/attributions/tracking/{tracking_number}", response_model=AttributionRead)
async def get_tracking_attribution(
    tracking_number: str,
    db: AsyncSession = Depends(get_db),
    brand_id: int = Depends(get_current_brand),
) -> AttributionRead:
    """Query responsibility attribution for a shipment with tenant data isolation (BR-10)."""
    stmt = (
        select(ShippingLabel)
        .options(
            selectinload(ShippingLabel.order),
            selectinload(ShippingLabel.dispatch),
        )
        .where(ShippingLabel.tracking_number == tracking_number)
    )
    res = await db.execute(stmt)
    label = res.scalar_one_or_none()

    if not label or not label.order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")

    # Tenant isolation: ensure brand owns the order
    if label.order.brand_id != brand_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: order belongs to another client",
        )

    service = FinancialEngineService()
    attribution = await service.attribute_shipment_responsibility(db, label)
    return AttributionRead.model_validate(attribution)


# =============================================================================
# 2. Freight Penalties
# =============================================================================


@router.get("/penalties", response_model=list[FreightPenaltyRead])
async def list_client_penalties(
    carrier_id: int | None = Query(default=None, description="Optional carrier ID filter"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    brand_id: int = Depends(get_current_brand),
) -> list[FreightPenaltyRead]:
    """Expose an API allowing clients to query penalties attributed to their orders (FR-06, BR-10)."""
    stmt = select(FreightPenalty).where(FreightPenalty.brand_id == brand_id)
    if carrier_id:
        stmt = stmt.where(FreightPenalty.carrier_id == carrier_id)

    stmt = stmt.order_by(FreightPenalty.calculated_at.desc()).limit(limit)
    res = await db.execute(stmt)
    penalties = res.scalars().all()
    return [FreightPenaltyRead.model_validate(p) for p in penalties]


@router.get("/carrier/{carrier_id}/penalties", response_model=list[FreightPenaltyRead])
async def list_carrier_penalties(
    carrier_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> list[FreightPenaltyRead]:
    """Expose an API allowing carriers to query penalties attributed to them (FR-07)."""
    stmt = (
        select(FreightPenalty)
        .where(
            FreightPenalty.carrier_id == carrier_id,
            FreightPenalty.is_carrier_payable.is_(True),
        )
        .order_by(FreightPenalty.calculated_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [FreightPenaltyRead.model_validate(p) for p in records]


# =============================================================================
# 3. Biweekly Financial Settlements & Netting (FR-05, BR-08)
# =============================================================================


@router.post("/settlements/generate", response_model=FinancialSettlementRead)
async def generate_settlement(
    payload: SettlementGenerateRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
) -> FinancialSettlementRead:
    """Generate or retrieve a biweekly settlement period and netting calculation (Admin only)."""
    service = FinancialEngineService()
    settlement = await service.generate_biweekly_settlement(
        db=db,
        carrier_id=payload.carrier_id,
        year=payload.year,
        month=payload.month,
        half=payload.half,
        notes=payload.notes,
    )
    await db.commit()
    await db.refresh(settlement)
    return FinancialSettlementRead.model_validate(settlement)


@router.get("/settlements/{settlement_id}", response_model=FinancialSettlementRead)
async def get_settlement_by_id(
    settlement_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> FinancialSettlementRead:
    """Retrieve details of a biweekly settlement period."""
    stmt = select(FinancialSettlement).where(FinancialSettlement.settlement_id == settlement_id)
    res = await db.execute(stmt)
    settlement = res.scalar_one_or_none()
    if not settlement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settlement not found")
    return FinancialSettlementRead.model_validate(settlement)


@router.get("/settlements/{settlement_id}/ledger", response_model=list[FinancialLedgerEntryRead])
async def list_settlement_ledger_entries(
    settlement_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_api_key),
) -> list[FinancialLedgerEntryRead]:
    """Review detailed audit trail and ledger movements for a settlement."""
    stmt = (
        select(FinancialLedgerEntry)
        .where(FinancialLedgerEntry.settlement_id == settlement_id)
        .order_by(FinancialLedgerEntry.entry_id.asc())
    )
    res = await db.execute(stmt)
    entries = res.scalars().all()
    return [FinancialLedgerEntryRead.model_validate(e) for e in entries]
