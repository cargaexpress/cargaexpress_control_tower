from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.schemas.carrier_state_mapping import (
    CarrierStateMappingRead,
    CarrierStateMappingResponse,
    CarrierStateMappingUpdate,
)
from app.security import require_admin
from app.services import carrier_state_mapping_service
from app.services.exceptions import EntityNotFoundError

# Routes use Spanish naming to match the project's current API convention; secured with ADMIN_API_KEY.
router = APIRouter(
    prefix="/api/v1/admin/mapeo-estados",
    tags=["admin: mapeo de estados"],
    dependencies=[Depends(require_admin)],
)

CARRIER_NOT_FOUND = "La transportadora no existe."


def _to_response(carrier: Carrier, rows: list[StateMapping]) -> CarrierStateMappingResponse:
    return CarrierStateMappingResponse(
        carrier_id=carrier.carrier_id,
        carrier_name=carrier.name,
        mappings=[CarrierStateMappingRead.model_validate(row) for row in rows],
    )


@router.get("/{transportadora_id}", response_model=CarrierStateMappingResponse)
async def get_carrier_mapping(
    transportadora_id: int = Path(gt=0), db: AsyncSession = Depends(get_db)
) -> CarrierStateMappingResponse:
    """Retrieve state mappings of a carrier directly as stored in the database."""
    try:
        carrier, rows = await carrier_state_mapping_service.get_carrier_mapping(db, transportadora_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARRIER_NOT_FOUND) from exc
    return _to_response(carrier, rows)


@router.put("/{transportadora_id}", response_model=CarrierStateMappingResponse)
async def update_carrier_mapping(
    payload: CarrierStateMappingUpdate,
    transportadora_id: int = Path(gt=0),
    db: AsyncSession = Depends(get_db),
) -> CarrierStateMappingResponse:
    """Replace the full carrier mapping set and apply immediately without restarting."""
    desired = {entry.raw_status: entry.canonical_status for entry in payload.mappings}
    try:
        carrier, rows = await carrier_state_mapping_service.replace_carrier_mapping(
            db, transportadora_id, desired
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARRIER_NOT_FOUND) from exc
    except IntegrityError as exc:
        # Another concurrent write won the race.
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El mapeo cambió mientras se actualizaba; vuelve a intentarlo.",
        ) from exc
    return _to_response(carrier, rows)
