from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.repositories import StateMappingRepository
from app.services.exceptions import ConcurrentUpdateConflictError, EntityNotFoundError
from app.services.state_mapping_cache import state_mapping_cache

# Business and data logic lives here; the router only handles HTTP concerns.


async def _read_mappings(db: AsyncSession, carrier_id: int) -> list[StateMapping]:
    return await StateMappingRepository.get_mappings_for_carrier(db, carrier_id)


async def get_carrier_mapping(
    db: AsyncSession, carrier_id: int
) -> tuple[Carrier, list[StateMapping]]:
    """Retrieve current state mappings for a carrier directly from the database (bypassing cache).

    Raises EntityNotFoundError if the carrier does not exist.
    """
    carrier = await StateMappingRepository.get_carrier(db, carrier_id)
    if carrier is None:
        raise EntityNotFoundError("carrier", carrier_id)
    return carrier, await _read_mappings(db, carrier_id)


async def replace_carrier_mapping(
    db: AsyncSession, carrier_id: int, desired: dict[str, str]
) -> tuple[Carrier, list[StateMapping]]:
    """Synchronize carrier mappings to EXACTLY match `desired` ({raw_status: canonical_status}).

    In a single transaction: inserts new statuses, updates changed meanings,
    and deletes obsolete ones. Unchanged entries retain their IDs.
    After commit, invalidates the cache so changes take effect immediately without restart.
    """
    # Lock the carrier row: concurrent PUT requests for the same carrier are serialized.
    carrier = await StateMappingRepository.get_carrier(db, carrier_id, with_for_update=True)
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

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConcurrentUpdateConflictError() from exc

    # Invalidate cache only after commit: if writing fails, valid cache is preserved.
    state_mapping_cache.invalidate()
    return carrier, await _read_mappings(db, carrier_id)
