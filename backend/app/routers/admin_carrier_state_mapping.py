from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.schemas.carrier_state_mapping import (
    CarrierStateMappingRead,
    CarrierStateMappingResponse,
    CarrierStateMappingUpdate,
)
from app.schemas.errors import HTTPErrorResponse
from app.security import require_admin
from app.services import carrier_state_mapping_service
from app.services.exceptions import ConcurrentUpdateConflictError, EntityNotFoundError

router = APIRouter(
    prefix="/api/v1/admin/carrier-state-mappings",
    tags=["admin: carrier state mapping"],
    dependencies=[Depends(require_admin)],
)

CARRIER_NOT_FOUND = "Carrier not found."


def _to_response(carrier: Carrier, rows: list[StateMapping]) -> CarrierStateMappingResponse:
    return CarrierStateMappingResponse(
        carrier_id=carrier.carrier_id,
        carrier_name=carrier.name,
        mappings=[CarrierStateMappingRead.model_validate(row) for row in rows],
    )


@router.get(
    "/{carrier_id}",
    response_model=CarrierStateMappingResponse,
    summary="Retrieve state mappings for a specific carrier (HU-15)",
    description="Retrieve all current status mappings configured for the given carrier directly from the database.",
    responses={
        200: {
            "description": "Carrier state mappings retrieved successfully.",
            "model": CarrierStateMappingResponse,
        },
        401: {
            "description": "Unauthorized access (missing or invalid X-Admin-Token).",
            "model": HTTPErrorResponse,
        },
        404: {"description": "Carrier not found.", "model": HTTPErrorResponse},
    },
)
async def get_carrier_mapping(
    carrier_id: int = Path(gt=0), db: AsyncSession = Depends(get_db)
) -> CarrierStateMappingResponse:
    """Retrieve state mappings of a carrier directly as stored in the database."""
    try:
        carrier, rows = await carrier_state_mapping_service.get_carrier_mapping(db, carrier_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARRIER_NOT_FOUND) from exc
    return _to_response(carrier, rows)


@router.put(
    "/{carrier_id}",
    response_model=CarrierStateMappingResponse,
    summary="Replace entire state mapping set for a carrier (HU-15)",
    description="Synchronize and replace the complete set of status mappings for a carrier in an atomic transaction.",
    responses={
        200: {
            "description": "Carrier state mappings synchronized successfully.",
            "model": CarrierStateMappingResponse,
        },
        401: {
            "description": "Unauthorized access (missing or invalid X-Admin-Token).",
            "model": HTTPErrorResponse,
        },
        404: {"description": "Carrier not found.", "model": HTTPErrorResponse},
        409: {"description": "Concurrent update conflict.", "model": HTTPErrorResponse},
        422: {
            "description": "Validation error in payload (e.g. invalid canonical status or duplicate raw status)."
        },
    },
)
async def update_carrier_mapping(
    payload: CarrierStateMappingUpdate,
    carrier_id: int = Path(gt=0),
    db: AsyncSession = Depends(get_db),
) -> CarrierStateMappingResponse:
    """Replace the full carrier mapping set and apply immediately without restarting."""
    desired = {entry.raw_status: entry.canonical_status for entry in payload.mappings}
    try:
        carrier, rows = await carrier_state_mapping_service.replace_carrier_mapping(
            db, carrier_id, desired
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARRIER_NOT_FOUND) from exc
    except ConcurrentUpdateConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _to_response(carrier, rows)
