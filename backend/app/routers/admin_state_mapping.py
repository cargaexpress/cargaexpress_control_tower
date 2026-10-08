from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.schemas.state_mapping import (
    StateMappingCreate,
    StateMappingRead,
    StateMappingResolved,
    StateMappingUpdate,
)
from app.security import require_admin
from app.services.state_mapping_cache import state_mapping_cache

router = APIRouter(
    prefix="/api/v1/admin/state-mappings",
    tags=["admin: state mapping"],
    dependencies=[Depends(require_admin)],
)

DUPLICATE_DETAIL = "Ya existe un mapeo para esa transportadora y ese estado."


@router.get("", response_model=list[StateMappingRead])
async def list_mappings(
    carrier_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> list[StateMapping]:
    """Lista los mapeos tal como están en la base de datos (no usa la caché)."""
    query = select(StateMapping).order_by(StateMapping.carrier_id, StateMapping.raw_status)
    if carrier_id is not None:
        query = query.where(StateMapping.carrier_id == carrier_id)
    return list((await db.scalars(query)).all())


# Declarado antes de /{mapping_id} para que "resolve" no se confunda con un id.
@router.get("/resolve", response_model=StateMappingResolved)
async def resolve_mapping(
    carrier_id: int = Query(gt=0), raw_status: str = Query(min_length=1)
) -> StateMappingResolved:
    """Traduce un estado de transportadora usando la caché en memoria."""
    canonical = await state_mapping_cache.translate(carrier_id, raw_status)
    if canonical is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay mapeo para ese estado.")
    return StateMappingResolved(
        carrier_id=carrier_id, raw_status=raw_status.strip(), canonical_status=canonical
    )


@router.post("", response_model=StateMappingRead, status_code=status.HTTP_201_CREATED)
async def create_mapping(
    payload: StateMappingCreate, db: AsyncSession = Depends(get_db)
) -> StateMapping:
    if await db.get(Carrier, payload.carrier_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La transportadora no existe.")

    mapping = StateMapping(**payload.model_dump())
    db.add(mapping)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_DETAIL)
    state_mapping_cache.invalidate()  # después del commit, nunca antes
    await db.refresh(mapping)
    return mapping


@router.patch("/{mapping_id}", response_model=StateMappingRead)
async def update_mapping(
    mapping_id: int, payload: StateMappingUpdate, db: AsyncSession = Depends(get_db)
) -> StateMapping:
    mapping = await db.get(StateMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El mapeo no existe.")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(mapping, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_DETAIL)
    state_mapping_cache.invalidate()
    await db.refresh(mapping)
    return mapping


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(mapping_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    mapping = await db.get(StateMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El mapeo no existe.")
    await db.delete(mapping)
    await db.commit()
    state_mapping_cache.invalidate()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
