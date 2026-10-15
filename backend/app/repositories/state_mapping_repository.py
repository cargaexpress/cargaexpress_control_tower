"""Repository for StateMapping database persistence.

Encapsulates all SQLAlchemy queries and direct ORM operations for state mappings,
insulating business services and caching layers from SQL schema details.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping


class StateMappingRepository:
    """Data access repository for StateMapping and related carrier checks."""

    @staticmethod
    async def get_all_pairs(session: AsyncSession) -> dict[tuple[int, str], str]:
        """Fetch all (carrier_id, raw_status) -> canonical_status mappings for cache population."""
        rows = await session.execute(
            select(StateMapping.carrier_id, StateMapping.raw_status, StateMapping.canonical_status)
        )
        return {(carrier_id, raw_status): canonical for carrier_id, raw_status, canonical in rows}

    @staticmethod
    async def list_by_carrier(
        session: AsyncSession, carrier_id: int | None = None
    ) -> list[StateMapping]:
        """Retrieve persisted mappings ordered by carrier and raw status."""
        query = select(StateMapping).order_by(StateMapping.carrier_id, StateMapping.raw_status)
        if carrier_id is not None:
            query = query.where(StateMapping.carrier_id == carrier_id)
        return list((await session.scalars(query)).all())

    @staticmethod
    async def get_by_id(session: AsyncSession, mapping_id: int) -> StateMapping | None:
        """Retrieve a single state mapping by primary key ID."""
        return await session.get(StateMapping, mapping_id)

    @staticmethod
    async def get_carrier(
        session: AsyncSession, carrier_id: int, with_for_update: bool = False
    ) -> Carrier | None:
        """Retrieve carrier by ID, optionally applying a row-level lock."""
        return await session.get(Carrier, carrier_id, with_for_update=with_for_update)

    @staticmethod
    async def get_mappings_for_carrier(
        session: AsyncSession, carrier_id: int
    ) -> list[StateMapping]:
        """Retrieve fresh state mappings for a carrier (with populate_existing)."""
        query = (
            select(StateMapping)
            .where(StateMapping.carrier_id == carrier_id)
            .order_by(StateMapping.raw_status)
            .execution_options(populate_existing=True)
        )
        return list((await session.scalars(query)).all())
