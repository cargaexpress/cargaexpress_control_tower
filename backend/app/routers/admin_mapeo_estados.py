from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.schemas.mapeo_estados import (
    MapeoEstadoSalida,
    MapeoEstadosActualizar,
    MapeoEstadosSalida,
)
from app.security import require_admin
from app.services import mapeo_estados_service
from app.services.exceptions import EntityNotFoundError

# Rutas en español según la convención de la API; protegidas con ADMIN_API_KEY (X-Admin-Token).
router = APIRouter(
    prefix="/api/v1/admin/mapeo-estados",
    tags=["admin: mapeo de estados"],
    dependencies=[Depends(require_admin)],
)

CARRIER_NOT_FOUND = "La transportadora no existe."


def _to_response(carrier: Carrier, rows: list[StateMapping]) -> MapeoEstadosSalida:
    return MapeoEstadosSalida(
        carrier_id=carrier.carrier_id,
        carrier_name=carrier.name,
        mappings=[MapeoEstadoSalida.model_validate(row) for row in rows],
    )


@router.get("/{transportadora_id}", response_model=MapeoEstadosSalida)
async def obtener_mapeo(
    transportadora_id: int = Path(gt=0), db: AsyncSession = Depends(get_db)
) -> MapeoEstadosSalida:
    """Consulta el mapeo de estados de una transportadora (tal como está en la base de datos)."""
    try:
        carrier, rows = await mapeo_estados_service.get_carrier_mapping(db, transportadora_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARRIER_NOT_FOUND) from exc
    return _to_response(carrier, rows)


@router.put("/{transportadora_id}", response_model=MapeoEstadosSalida)
async def actualizar_mapeo(
    payload: MapeoEstadosActualizar,
    transportadora_id: int = Path(gt=0),
    db: AsyncSession = Depends(get_db),
) -> MapeoEstadosSalida:
    """Reemplaza el mapeo completo de la transportadora y lo aplica sin reiniciar el servicio."""
    desired = {entry.raw_status: entry.canonical_status for entry in payload.mappings}
    try:
        carrier, rows = await mapeo_estados_service.replace_carrier_mapping(
            db, transportadora_id, desired
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CARRIER_NOT_FOUND) from exc
    except IntegrityError as exc:
        # Otra escritura (por ejemplo un POST de /state-mappings) ganó la carrera.
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "El mapeo cambió mientras se actualizaba; vuelve a intentarlo.",
        ) from exc
    return _to_response(carrier, rows)
