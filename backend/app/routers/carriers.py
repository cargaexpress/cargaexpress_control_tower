import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.carrier import Carrier
from app.schemas.carrier import CarrierRead
from app.security import get_current_carrier, require_api_key

logger = logging.getLogger("cargaexpress.carriers_router")

router = APIRouter(prefix="/api/v1/carriers", tags=["carriers"])


@router.get("/me", response_model=CarrierRead)
async def get_my_carrier_profile(
    db: AsyncSession = Depends(get_db),
    carrier_id: int = Depends(get_current_carrier),
) -> CarrierRead:
    """Retrieve profile and integration information for the currently authenticated carrier."""
    carrier = await db.get(Carrier, carrier_id)
    if carrier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Carrier with ID {carrier_id} not found.",
        )
    return CarrierRead.model_validate(carrier)


@router.get("", response_model=list[CarrierRead], dependencies=[Depends(require_api_key)])
async def list_all_carriers(
    db: AsyncSession = Depends(get_db),
) -> list[CarrierRead]:
    """List all registered carriers in the Control Tower."""
    stmt = select(Carrier).order_by(Carrier.carrier_id)
    res = await db.execute(stmt)
    carriers = res.scalars().all()
    return [CarrierRead.model_validate(c) for c in carriers]


@router.get("/{carrier_id}", response_model=CarrierRead, dependencies=[Depends(require_api_key)])
async def get_carrier_by_id(
    carrier_id: Annotated[int, Path(gt=0, description="Carrier primary key")],
    db: AsyncSession = Depends(get_db),
) -> CarrierRead:
    """Retrieve carrier details by carrier ID."""
    carrier = await db.get(Carrier, carrier_id)
    if carrier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Carrier with ID {carrier_id} not found.",
        )
    return CarrierRead.model_validate(carrier)
