"""In-memory cache for state_mapping table (RIWI-60).

How it works:
- First lookup loads the entire mapping table into an in-memory dictionary;
  subsequent queries are answered without hitting the database.
- When an admin endpoint creates, updates, or deletes a mapping, it calls
  `invalidate()` (after commit). The next query reloads fresh data from DB,
  making updates instantly visible without restarting the service.
- Time-to-live fallback (TTL): if another process updates the table (e.g.
  a second worker or replica), this cache picks up changes once TTL expires.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.config import settings
from app.database import AsyncSessionLocal
from app.repositories import StateMappingRepository

MappingKey = tuple[int, str]  # (carrier_id, raw_status)
Loader = Callable[[], Awaitable[dict[MappingKey, str]]]

# Process-local memory avoids a database read per event; TTL covers external edits.
# This is simpler than Redis for the current single-backend deployment.


async def load_mappings_from_db() -> dict[MappingKey, str]:
    # Dedicated session (not the request session) to read committed database state.
    async with AsyncSessionLocal() as session:
        return await StateMappingRepository.get_all_pairs(session)


class StateMappingCache:
    def __init__(
        self,
        loader: Loader,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader
        self._ttl = ttl_seconds
        self._clock = clock
        self._data: dict[MappingKey, str] | None = None
        self._loaded_at = 0.0
        self._generation = 0  # increments on each invalidate() call
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        """Discard cached data; next query will reload from database."""
        self._generation += 1
        self._data = None

    def _is_fresh(self) -> bool:
        return self._data is not None and (self._clock() - self._loaded_at) < self._ttl

    async def _snapshot(self) -> dict[MappingKey, str]:
        if self._is_fresh():
            return self._data  # type: ignore[return-value]
        async with self._lock:
            if self._is_fresh():  # another concurrent request reloaded while waiting
                return self._data  # type: ignore[return-value]
            generation = self._generation
            data = await self._loader()
            # A generation check prevents an in-flight stale read from being cached.
            if generation == self._generation:
                self._data = data
                self._loaded_at = self._clock()
            return data

    async def translate(self, carrier_id: int, raw_status: str) -> str | None:
        """Translate carrier raw status to canonical status, or None if no mapping exists."""
        return (await self._snapshot()).get((carrier_id, raw_status.strip()))


state_mapping_cache = StateMappingCache(
    load_mappings_from_db, settings.state_mapping_cache_ttl_seconds
)
