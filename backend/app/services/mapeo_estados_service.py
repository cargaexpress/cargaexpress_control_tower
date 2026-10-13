from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.services.exceptions import EntityNotFoundError
from app.services.state_mapping_cache import state_mapping_cache

# La lógica de datos vive aquí; el router solo traduce HTTP.
# populate_existing garantiza leer valores frescos (updated_at lo fija la base de datos).


async def _read_mappings(db: AsyncSession, carrier_id: int) -> list[StateMapping]:
    query = (
        select(StateMapping)
        .where(StateMapping.carrier_id == carrier_id)
        .order_by(StateMapping.raw_status)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(query)).all())


async def get_carrier_mapping(db: AsyncSession, carrier_id: int) -> tuple[Carrier, list[StateMapping]]:
    """Mapeo actual de una transportadora, leído de la base de datos (no de la caché).

    Lanza EntityNotFoundError si la transportadora no existe.
    """
    carrier = await db.get(Carrier, carrier_id)
    if carrier is None:
        raise EntityNotFoundError("carrier", carrier_id)
    return carrier, await _read_mappings(db, carrier_id)


async def replace_carrier_mapping(
    db: AsyncSession, carrier_id: int, desired: dict[str, str]
) -> tuple[Carrier, list[StateMapping]]:
    """Deja el mapeo de la transportadora EXACTAMENTE igual a `desired` ({raw_status: canonical_status}).

    En una sola transacción: crea los estados nuevos, actualiza los que cambiaron de
    significado y elimina los que ya no vienen. Los estados que no cambian conservan su id.
    Después de confirmar, invalida la caché para que el cambio se vea sin reiniciar.
    """
    # Bloquea la fila de la transportadora: dos PUT simultáneos a la misma se ejecutan en fila.
    carrier = await db.get(Carrier, carrier_id, with_for_update=True)
    if carrier is None:
        raise EntityNotFoundError("carrier", carrier_id)

    existing = {row.raw_status: row for row in await _read_mappings(db, carrier_id)}
    for raw_status, canonical_status in desired.items():
        row = existing.pop(raw_status, None)
        if row is None:
            db.add(
                StateMapping(
                    carrier_id=carrier_id, raw_status=raw_status, canonical_status=canonical_status
                )
            )
        elif row.canonical_status != canonical_status:
            row.canonical_status = canonical_status
    for removed in existing.values():
        await db.delete(removed)

    await db.commit()
    # Solo después del commit: si la escritura falla, la caché vigente no se descarta.
    state_mapping_cache.invalidate()
    return carrier, await _read_mappings(db, carrier_id)
