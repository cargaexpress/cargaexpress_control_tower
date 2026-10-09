"""Pruebas unitarias de la caché de state_mapping (sin base de datos)."""

import asyncio

from app.services.state_mapping_cache import StateMappingCache


# Fake loader and clock make cache behavior testable without PostgreSQL or waiting.
# El cargador y reloj falsos prueban la caché sin PostgreSQL ni esperas reales.
class FakeLoader:
    """Cuenta cuántas veces se "lee la base de datos" y permite cambiar sus datos."""

    def __init__(self, data):
        self.data = data
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        return dict(self.data)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


async def test_second_lookup_is_served_from_memory():
    loader = FakeLoader({(1, "SENT"): "IN_TRANSIT"})
    cache = StateMappingCache(loader, ttl_seconds=300)

    assert await cache.translate(1, "SENT") == "IN_TRANSIT"
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"
    assert await cache.translate(1, "OTHER") is None

    assert loader.calls == 1


async def test_invalidate_makes_changes_visible_without_restart():
    loader = FakeLoader({(1, "SENT"): "IN_TRANSIT"})
    cache = StateMappingCache(loader, ttl_seconds=300)
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"

    loader.data = {(1, "SENT"): "DELIVERED"}  # alguien edita la tabla...
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"  # ...la caché aún no lo sabe

    cache.invalidate()  # el endpoint admin avisa tras guardar

    assert await cache.translate(1, "SENT") == "DELIVERED"
    assert loader.calls == 2


async def test_ttl_expiry_reloads_changes_made_by_other_processes():
    clock = FakeClock()
    loader = FakeLoader({(1, "SENT"): "IN_TRANSIT"})
    cache = StateMappingCache(loader, ttl_seconds=60, clock=clock)
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"

    loader.data = {(1, "SENT"): "DELIVERED"}
    clock.now = 59
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"  # aún vigente
    clock.now = 61
    assert await cache.translate(1, "SENT") == "DELIVERED"  # venció el TTL


async def test_lookup_ignores_surrounding_spaces():
    cache = StateMappingCache(FakeLoader({(1, "En tránsito"): "IN_TRANSIT"}), ttl_seconds=300)

    assert await cache.translate(1, "  En tránsito ") == "IN_TRANSIT"


async def test_concurrent_lookups_load_only_once():
    loader = FakeLoader({(1, "SENT"): "IN_TRANSIT"})
    cache = StateMappingCache(loader, ttl_seconds=300)

    results = await asyncio.gather(*(cache.translate(1, "SENT") for _ in range(20)))

    assert results == ["IN_TRANSIT"] * 20
    assert loader.calls == 1


async def test_invalidation_during_a_load_does_not_cache_stale_data():
    """Si se invalida mientras se lee, lo leído puede ser anterior al cambio."""
    started = asyncio.Event()
    release = asyncio.Event()
    state = {"data": {(1, "SENT"): "IN_TRANSIT"}, "calls": 0}

    async def slow_loader():
        state["calls"] += 1
        snapshot = dict(state["data"])  # lee los datos viejos...
        started.set()
        await release.wait()  # ...y tarda en terminar
        return snapshot

    cache = StateMappingCache(slow_loader, ttl_seconds=300)
    first = asyncio.create_task(cache.translate(1, "SENT"))
    await started.wait()

    state["data"] = {(1, "SENT"): "DELIVERED"}  # se confirma un cambio
    cache.invalidate()
    release.set()
    await first

    # La lectura vieja no debe haber quedado guardada: la siguiente consulta recarga.
    assert await cache.translate(1, "SENT") == "DELIVERED"
    assert state["calls"] == 2
