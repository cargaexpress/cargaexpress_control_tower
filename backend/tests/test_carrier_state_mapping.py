"""HU-15: GET/PUT /api/v1/admin/carrier-state-mappings/{carrier_id}.

Uses fixtures from conftest.py (isolated test database). Data is seeded
using `db_session`, never touching runtime DB, so tests work whether
TEST_DATABASE_URL is a dedicated test database or matches DATABASE_URL.
"""

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.services.state_mapping_cache as cache_module
from app.config import settings
from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.services.state_mapping_cache import state_mapping_cache

BASE = "/api/v1/admin/carrier-state-mappings"
RESOLVE = "/api/v1/admin/state-mappings/resolve"  # HU-12 endpoint reading from cache
ADMIN = {"X-Admin-Token": "test-admin-key"}


@pytest.fixture(autouse=True)
def admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")


@pytest_asyncio.fixture(autouse=True)
async def cache_reads_test_database(db_session, monkeypatch):
    """The application cache must read from the test database, not runtime DB."""
    maker = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(cache_module, "AsyncSessionLocal", maker)
    state_mapping_cache.invalidate()
    yield
    state_mapping_cache.invalidate()


async def _make_carrier(db_session, name):
    carrier = Carrier(name=name, integration_type="simulated", status="active")
    db_session.add(carrier)
    await db_session.commit()
    return carrier.carrier_id


@pytest_asyncio.fixture
async def carrier_id(db_session):
    return await _make_carrier(db_session, "pytest-carrier")


@pytest_asyncio.fixture
async def other_carrier_id(db_session):
    return await _make_carrier(db_session, "pytest-other-carrier")


async def _seed(db_session, carrier_id, mappings):
    db_session.add_all(
        StateMapping(carrier_id=carrier_id, raw_status=raw, canonical_status=canonical)
        for raw, canonical in mappings.items()
    )
    await db_session.commit()


def _as_dict(response_json):
    return {m["raw_status"]: m["canonical_status"] for m in response_json["mappings"]}


async def _put(client, carrier_id, mappings):
    body = {"mappings": [{"raw_status": r, "canonical_status": c} for r, c in mappings.items()]}
    return await client.put(f"{BASE}/{carrier_id}", json=body, headers=ADMIN)


# ---------- RIWI-73: GET ----------


async def test_get_returns_the_mapping_of_that_carrier_only_and_sorted(
    client, db_session, carrier_id, other_carrier_id
):
    await _seed(db_session, carrier_id, {"B": "IN_TRANSIT", "A": "CREATED"})
    await _seed(db_session, other_carrier_id, {"Z": "DELIVERED"})

    response = await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)

    assert response.status_code == 200
    body = response.json()
    assert body["carrier_id"] == carrier_id
    assert body["carrier_name"] == "pytest-carrier"
    assert [m["raw_status"] for m in body["mappings"]] == ["A", "B"]
    assert set(body["mappings"][0]) == {"id", "raw_status", "canonical_status", "updated_at"}


async def test_get_carrier_without_mappings_returns_an_empty_list(client, carrier_id):
    response = await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)

    assert response.status_code == 200
    assert response.json()["mappings"] == []


async def test_get_unknown_carrier_returns_404(client):
    response = await client.get(f"{BASE}/999999999", headers=ADMIN)

    assert response.status_code == 404


async def test_get_always_shows_what_is_in_the_database_even_with_a_warm_cache(
    client, db_session, carrier_id
):
    await _seed(db_session, carrier_id, {"A": "CREATED"})
    await state_mapping_cache.translate(carrier_id, "A")  # warms up cache

    await _seed(db_session, carrier_id, {"B": "DELIVERED"})  # direct change in database

    response = await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)
    assert _as_dict(response.json()) == {"A": "CREATED", "B": "DELIVERED"}


# ---------- RIWI-74: PUT ----------


async def test_put_replaces_the_whole_mapping(client, db_session, carrier_id):
    await _seed(db_session, carrier_id, {"A": "CREATED", "B": "IN_TRANSIT", "C": "DELIVERED"})

    response = await _put(
        client, carrier_id, {"B": "DELIVERED", "C": "DELIVERED", "D": "EXCEPTION"}
    )

    assert response.status_code == 200
    expected = {"B": "DELIVERED", "C": "DELIVERED", "D": "EXCEPTION"}  # A disappears
    assert _as_dict(response.json()) == expected
    assert _as_dict((await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)).json()) == expected


async def test_put_keeps_ids_of_unchanged_entries_and_ignores_other_carriers(
    client, db_session, carrier_id, other_carrier_id
):
    await _seed(db_session, carrier_id, {"A": "CREATED", "B": "IN_TRANSIT"})
    await _seed(db_session, other_carrier_id, {"A": "DELIVERED"})
    before = {
        m["raw_status"]: m["id"]
        for m in (await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)).json()["mappings"]
    }

    await _put(client, carrier_id, {"A": "CREATED", "B": "DELIVERED"})

    after = (await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)).json()["mappings"]
    assert {m["raw_status"]: m["id"] for m in after} == before  # updated in place
    other = await client.get(f"{BASE}/{other_carrier_id}", headers=ADMIN)
    assert _as_dict(other.json()) == {"A": "DELIVERED"}  # another carrier was not touched


async def test_put_is_idempotent(client, carrier_id):
    mappings = {"A": "CREATED", "B": "IN_TRANSIT"}

    first = await _put(client, carrier_id, mappings)
    second = await _put(client, carrier_id, mappings)

    assert first.status_code == second.status_code == 200
    assert [
        (m["id"], m["raw_status"], m["canonical_status"]) for m in first.json()["mappings"]
    ] == [(m["id"], m["raw_status"], m["canonical_status"]) for m in second.json()["mappings"]]


async def test_put_normalizes_spaces_and_case(client, carrier_id):
    response = await client.put(
        f"{BASE}/{carrier_id}",
        json={"mappings": [{"raw_status": "  En tránsito ", "canonical_status": " in_transit "}]},
        headers=ADMIN,
    )

    assert response.status_code == 200
    assert _as_dict(response.json()) == {"En tránsito": "IN_TRANSIT"}


async def test_put_unknown_carrier_returns_404(client):
    response = await _put(client, 999_999_999, {"A": "CREATED"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"mappings": [{"raw_status": "A", "canonical_status": "NOPE"}]},
        {
            "mappings": [{"raw_status": "A", "canonical_status": "CANCELLED"}]
        },  # no longer in catalog
        {"mappings": [{"raw_status": "   ", "canonical_status": "CREATED"}]},
        {"mappings": [{"raw_status": "x" * 101, "canonical_status": "CREATED"}]},
        {
            "mappings": [
                {"raw_status": "A", "canonical_status": "CREATED"},
                {"raw_status": " A ", "canonical_status": "DELIVERED"},
            ]
        },
        {"mappings": []},
        {},
    ],
    ids=[
        "invalid-canonical",
        "obsolete-canonical",
        "empty-raw",
        "too-long-raw",
        "duplicate-raw",
        "empty-list",
        "missing-mappings",
    ],
)
async def test_put_with_invalid_body_returns_422_and_changes_nothing(
    client, db_session, carrier_id, body
):
    await _seed(db_session, carrier_id, {"KEEP": "CREATED"})

    response = await client.put(f"{BASE}/{carrier_id}", json=body, headers=ADMIN)

    assert response.status_code == 422
    after = await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)
    assert _as_dict(after.json()) == {"KEEP": "CREATED"}


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc"])
async def test_non_positive_or_non_numeric_carrier_id_returns_422(client, bad_id):
    assert (await client.get(f"{BASE}/{bad_id}", headers=ADMIN)).status_code == 422
    assert (await _put(client, bad_id, {"A": "CREATED"})).status_code == 422


# ---------- Security ----------


@pytest.mark.parametrize("method", ["get", "put"])
async def test_admin_token_is_required(client, carrier_id, monkeypatch, method):
    kwargs = (
        {"json": {"mappings": [{"raw_status": "A", "canonical_status": "CREATED"}]}}
        if method == "put"
        else {}
    )
    url = f"{BASE}/{carrier_id}"

    assert (await client.request(method, url, **kwargs)).status_code == 401
    assert (
        await client.request(method, url, headers={"X-Admin-Token": "invalid-token"}, **kwargs)
    ).status_code == 401

    monkeypatch.setattr(settings, "admin_api_key", "")  # no key configured
    assert (await client.request(method, url, headers=ADMIN, **kwargs)).status_code == 503


# ---------- RIWI-75: change is reflected without restarting the service ----------


async def test_put_change_is_reflected_without_restarting_the_service(
    client, db_session, carrier_id
):
    """The same application, the same process, and the same cache instance from start to finish."""
    await _seed(db_session, carrier_id, {"SENT": "IN_TRANSIT", "LOST": "EXCEPTION"})

    # 1) Cache is warmed with current mapping.
    assert await state_mapping_cache.translate(carrier_id, "SENT") == "IN_TRANSIT"
    assert await state_mapping_cache.translate(carrier_id, "LOST") == "EXCEPTION"

    # 2) Proof that cache is actively used: direct DB change (bypassing API) is NOT visible yet.
    await db_session.execute(
        update(StateMapping)
        .where(StateMapping.carrier_id == carrier_id, StateMapping.raw_status == "SENT")
        .values(canonical_status="RETURNED")
    )
    await db_session.commit()
    assert await state_mapping_cache.translate(carrier_id, "SENT") == "IN_TRANSIT"

    # 3) Admin updates mapping via PUT endpoint.
    response = await _put(client, carrier_id, {"SENT": "DELIVERED", "NEW": "CREATED"})
    assert response.status_code == 200

    # 4) Without restarting, change is immediately visible in the cache...
    assert await state_mapping_cache.translate(carrier_id, "SENT") == "DELIVERED"
    assert await state_mapping_cache.translate(carrier_id, "NEW") == "CREATED"
    assert await state_mapping_cache.translate(carrier_id, "LOST") is None

    # ...in HU-12 endpoint resolving via cache...
    resolved = await client.get(
        RESOLVE, params={"carrier_id": carrier_id, "raw_status": "SENT"}, headers=ADMIN
    )
    assert resolved.json()["canonical_status"] == "DELIVERED"
    lost = await client.get(
        RESOLVE, params={"carrier_id": carrier_id, "raw_status": "LOST"}, headers=ADMIN
    )
    assert lost.status_code == 404

    # ...and in GET endpoint.
    assert _as_dict((await client.get(f"{BASE}/{carrier_id}", headers=ADMIN)).json()) == {
        "SENT": "DELIVERED",
        "NEW": "CREATED",
    }
