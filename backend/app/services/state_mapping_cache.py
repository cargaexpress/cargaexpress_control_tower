"""Caché en memoria de la tabla state_mapping (RIWI-60).

Cómo funciona:
- La primera consulta carga TODA la tabla en un diccionario en memoria; las
  siguientes se responden sin tocar la base de datos.
- Cuando el endpoint admin crea, edita o elimina un mapeo, llama a `invalidate()`
  (después del commit). La siguiente consulta recarga desde la base de datos, así
  los cambios se ven al instante y sin reiniciar el servicio.
- Respaldo por tiempo (TTL): si OTRO proceso modifica la tabla (por ejemplo un
  segundo worker o una réplica), esta caché lo notará a más tardar al vencer el TTL.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.state_mapping import StateMapping

MappingKey = tuple[int, str]  # (carrier_id, raw_status)
Loader = Callable[[], Awaitable[dict[MappingKey, str]]]

# Process-local memory avoids a database read per event; TTL covers external edits.
# This is simpler than Redis for the current single-backend deployment.
# La memoria local evita consultar la BD por evento; TTL detecta cambios externos.
# Es más simple que Redis para el despliegue actual de un solo backend.

async def load_mappings_from_db() -> dict[MappingKey, str]:
    # Sesión propia (no la de la petición) para leer siempre datos ya confirmados.
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(StateMapping.carrier_id, StateMapping.raw_status, StateMapping.canonical_status)
        )
        return {(carrier_id, raw_status): canonical for carrier_id, raw_status, canonical in rows}


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
        self._generation = 0  # sube con cada invalidate()
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        """Descarta lo cargado; la próxima consulta vuelve a leer la base de datos."""
        self._generation += 1
        self._data = None

    def _is_fresh(self) -> bool:
        return self._data is not None and (self._clock() - self._loaded_at) < self._ttl

    async def _snapshot(self) -> dict[MappingKey, str]:
        if self._is_fresh():
            return self._data  # type: ignore[return-value]
        async with self._lock:
            if self._is_fresh():  # otra petición ya recargó mientras esperábamos
                return self._data  # type: ignore[return-value]
            generation = self._generation
            data = await self._loader()
            # A generation check prevents an in-flight stale read from being cached.
            # La generación evita guardar como vigente una lectura obsoleta en curso.
            if generation == self._generation:
                self._data = data
                self._loaded_at = self._clock()
            return data

    async def translate(self, carrier_id: int, raw_status: str) -> str | None:
        """Estado canónico para el estado de la transportadora, o None si no hay mapeo."""
        return (await self._snapshot()).get((carrier_id, raw_status.strip()))


state_mapping_cache = StateMappingCache(
    load_mappings_from_db, settings.state_mapping_cache_ttl_seconds
)
