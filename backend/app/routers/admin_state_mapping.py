from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.state_mapping import StateMapping
from app.schemas.state_mapping import (
    StateMappingCreate,
    StateMappingRead,
    StateMappingResolved,
    StateMappingUpdate,
)
from app.security import require_admin
from app.services import state_mapping_service
from app.services.exceptions import DuplicateMappingError, EntityNotFoundError
from app.services.state_mapping_cache import state_mapping_cache

# Protect the entire admin surface; public carrier events do not need this key.
# A shared key is used instead of JWT because this scope has no user sessions or roles.
router = APIRouter(
    prefix="/api/v1/admin/state-mappings",
    tags=["admin: state mapping"],
    dependencies=[Depends(require_admin)],
)

CARRIER_NOT_FOUND = "Carrier does not exist."
MAPPING_NOT_FOUND = "Mapping does not exist."


@router.get("", response_model=list[StateMappingRead])
async def list_mappings(
    carrier_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
) -> list[StateMapping]:
    """Read current persisted mappings."""
    return await state_mapping_service.list_mappings(db, carrier_id)


# Declared before /{mapping_id} so "resolve" is not parsed as an id parameter.
@router.get("/resolve", response_model=StateMappingResolved)
async def resolve_mapping(
    carrier_id: int = Query(gt=0), raw_status: str = Query(min_length=1)
) -> StateMappingResolved:
    """Translate a carrier status from cache."""
    canonical = await state_mapping_cache.translate(carrier_id, raw_status)
    if canonical is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mapping found for this status.")
    return StateMappingResolved(
        carrier_id=carrier_id, raw_status=raw_status.strip(), canonical_status=canonical
    )


@router.post("", response_model=StateMappingRead, status_code=status.HTTP_201_CREATED)
async def create_mapping(
    payload: StateMappingCreate, db: AsyncSession = Depends(get_db)
) -> StateMapping:
    try:
        return await state_mapping_service.create_mapping(db, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARRIER_NOT_FOUND) from exc
    except DuplicateMappingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.patch("/{mapping_id}", response_model=StateMappingRead)
async def update_mapping(
    mapping_id: int, payload: StateMappingUpdate, db: AsyncSession = Depends(get_db)
) -> StateMapping:
    try:
        return await state_mapping_service.update_mapping(db, mapping_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MAPPING_NOT_FOUND) from exc
    except DuplicateMappingError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(mapping_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await state_mapping_service.delete_mapping(db, mapping_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, MAPPING_NOT_FOUND) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
