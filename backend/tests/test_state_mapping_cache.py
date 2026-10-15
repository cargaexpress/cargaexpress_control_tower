"""Unit tests for state_mapping cache (in-memory, no database)."""

import asyncio

from app.services.state_mapping_cache import StateMappingCache


# Fake loader and clock make cache behavior testable without PostgreSQL or waiting.
class FakeLoader:
    """Tracks how many times the database is "read" and allows updating test data."""

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

    loader.data = {(1, "SENT"): "DELIVERED"}  # table is edited externally...
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"  # ...cache does not know yet

    cache.invalidate()  # admin endpoint notifies after commit

    assert await cache.translate(1, "SENT") == "DELIVERED"
    assert loader.calls == 2


async def test_ttl_expiry_reloads_changes_made_by_other_processes():
    clock = FakeClock()
    loader = FakeLoader({(1, "SENT"): "IN_TRANSIT"})
    cache = StateMappingCache(loader, ttl_seconds=60, clock=clock)
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"

    loader.data = {(1, "SENT"): "DELIVERED"}
    clock.now = 59
    assert await cache.translate(1, "SENT") == "IN_TRANSIT"  # still valid
    clock.now = 61
    assert await cache.translate(1, "SENT") == "DELIVERED"  # TTL expired


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
    """If invalidated during a load, stale loaded data must not be cached."""
    started = asyncio.Event()
    release = asyncio.Event()
    state = {"data": {(1, "SENT"): "IN_TRANSIT"}, "calls": 0}

    async def slow_loader():
        state["calls"] += 1
        snapshot = dict(state["data"])  # reads old data...
        started.set()
        await release.wait()  # ...and takes time to finish
        return snapshot

    cache = StateMappingCache(slow_loader, ttl_seconds=300)
    first = asyncio.create_task(cache.translate(1, "SENT"))
    await started.wait()

    state["data"] = {(1, "SENT"): "DELIVERED"}  # a change is committed
    cache.invalidate()
    release.set()
    await first

    # Old read should not be retained: next lookup triggers a reload.
    assert await cache.translate(1, "SENT") == "DELIVERED"
    assert state["calls"] == 2
