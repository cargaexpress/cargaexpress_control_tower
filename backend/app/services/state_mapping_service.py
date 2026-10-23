"""Service layer for state mapping CRUD operations (HU-12).

Isolates database persistence and cache invalidation from HTTP routing concerns.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.state_mapping import StateMapping
from app.repositories import StateMappingRepository
from app.schemas.state_mapping import StateMappingCreate, StateMappingUpdate
from app.services.exceptions import DuplicateMappingError, EntityNotFoundError
from app.services.state_mapping_cache import state_mapping_cache


async def list_mappings(db: AsyncSession, carrier_id: int | None = None) -> list[StateMapping]:
    """Retrieve persisted mappings, optionally filtered by carrier."""
    return await StateMappingRepository.list_by_carrier(db, carrier_id)


async def create_mapping(db: AsyncSession, payload: StateMappingCreate) -> StateMapping:
    """Create a new state mapping for a carrier.

    Raises:
        EntityNotFoundError: If the carrier does not exist.
        DuplicateMappingError: If a mapping for this carrier and raw_status already exists.
    """
    carrier = await StateMappingRepository.get_carrier(db, payload.carrier_id)
    if carrier is None:
        raise EntityNotFoundError("carrier", payload.carrier_id)

    mapping = StateMapping(**payload.model_dump())
    db.add(mapping)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateMappingError() from exc

    state_mapping_cache.invalidate()
    await db.refresh(mapping)
    return mapping


async def update_mapping(
    db: AsyncSession, mapping_id: int, payload: StateMappingUpdate
) -> StateMapping:
    """Update an existing state mapping.

    Raises:
        EntityNotFoundError: If the mapping does not exist.
        DuplicateMappingError: If the updated raw_status conflicts with an existing mapping.
    """
    mapping = await StateMappingRepository.get_by_id(db, mapping_id)
    if mapping is None:
        raise EntityNotFoundError("mapping", mapping_id)

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(mapping, field, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateMappingError() from exc

    state_mapping_cache.invalidate()
    await db.refresh(mapping)
    return mapping


async def delete_mapping(db: AsyncSession, mapping_id: int) -> None:
    """Delete an existing state mapping.

    Raises:
        EntityNotFoundError: If the mapping does not exist.
    """
    mapping = await StateMappingRepository.get_by_id(db, mapping_id)
    if mapping is None:
        raise EntityNotFoundError("mapping", mapping_id)

    await db.delete(mapping)
    await db.commit()
    state_mapping_cache.invalidate()
