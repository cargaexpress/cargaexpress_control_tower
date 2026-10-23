"""Tests for state_mapping admin endpoint.

- Security tests do not require a database.
- End-to-end tests use real PostgreSQL with migrations already applied
  (`alembic upgrade head`); if the database is unavailable, they are skipped.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.main import app
from app.models.carrier import Carrier
from app.models.state_mapping import StateMapping
from app.services.state_mapping_cache import state_mapping_cache
from tests.conftest import TestSessionLocal as AsyncSessionLocal
from tests.conftest import test_engine as engine

URL = "/api/v1/admin/state-mappings"
ADMIN = {"X-Admin-Token": "test-admin-key"}
TEST_CARRIER_NAME = "pytest-carrier"


# ---------- Security (without database) ----------


def test_admin_is_disabled_when_no_key_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "")

    response = TestClient(app).get(URL, headers=ADMIN)

    assert response.status_code == 503


def test_admin_rejects_missing_or_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    client = TestClient(app)

    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={"X-Admin-Token": "invalid-token"}).status_code == 401


# ---------- Full flow (real PostgreSQL) ----------


@pytest.fixture
async def db_ready():
    await engine.dispose()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1 FROM state_mapping LIMIT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("PostgreSQL with migrations applied is unavailable")
    yield
    await engine.dispose()  # each test uses its own event loop


@pytest.fixture
async def carrier_id(db_ready):
    async with AsyncSessionLocal() as session:
        carrier = Carrier(name=TEST_CARRIER_NAME, integration_type="simulated", status="active")
        session.add(carrier)
        await session.commit()
        created_id = carrier.carrier_id
    state_mapping_cache.invalidate()
    yield created_id
    async with AsyncSessionLocal() as session:
        await session.execute(delete(StateMapping).where(StateMapping.carrier_id == created_id))
        await session.execute(delete(Carrier).where(Carrier.carrier_id == created_id))
        await session.commit()
    state_mapping_cache.invalidate()


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def resolve(client, carrier_id, source_status):
    return await client.get(
        f"{URL}/resolve",
        params={"carrier_id": carrier_id, "raw_status": source_status},
        headers=ADMIN,
    )


async def test_changes_are_reflected_without_restarting(client, carrier_id):
    created = await client.post(
        URL,
        json={
            "carrier_id": carrier_id,
            "raw_status": " SHIPPED ",
            "canonical_status": "in_transit",
        },
        headers=ADMIN,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["raw_status"] == "SHIPPED"  # without surrounding whitespace
    assert body["canonical_status"] == "IN_TRANSIT"  # normalized to uppercase

    # First lookup: populates the cache.
    first = await resolve(client, carrier_id, "SHIPPED")
    assert first.json()["canonical_status"] == "IN_TRANSIT"

    # Edit: cache already held old value, but change is visible immediately.
    patched = await client.patch(
        f"{URL}/{body['id']}", json={"canonical_status": "DELIVERED"}, headers=ADMIN
    )
    assert patched.status_code == 200
    assert (await resolve(client, carrier_id, "SHIPPED")).json()["canonical_status"] == "DELIVERED"

    # Delete: stops resolving.
    deleted = await client.delete(f"{URL}/{body['id']}", headers=ADMIN)
    assert deleted.status_code == 204
    assert (await resolve(client, carrier_id, "SHIPPED")).status_code == 404


async def test_create_validations(client, carrier_id):
    payload = {"carrier_id": carrier_id, "raw_status": "X", "canonical_status": "DELIVERED"}
    assert (await client.post(URL, json=payload, headers=ADMIN)).status_code == 201

    duplicate = await client.post(URL, json=payload, headers=ADMIN)
    assert duplicate.status_code == 409

    unknown_carrier = await client.post(
        URL, json={**payload, "carrier_id": 999_999_999}, headers=ADMIN
    )
    assert unknown_carrier.status_code == 404

    bad_canonical = await client.post(
        URL, json={**payload, "canonical_status": "NOPE"}, headers=ADMIN
    )
    assert bad_canonical.status_code == 422
    obsolete_canonical = await client.post(
        URL, json={**payload, "canonical_status": "CANCELLED"}, headers=ADMIN
    )
    assert obsolete_canonical.status_code == 422

    blank_source = await client.post(URL, json={**payload, "raw_status": "   "}, headers=ADMIN)
    assert blank_source.status_code == 422


async def test_database_rejects_noncanonical_status(client, carrier_id):
    async with AsyncSessionLocal() as session:
        session.add(
            StateMapping(
                carrier_id=carrier_id,
                raw_status="INVALID",
                canonical_status="CANCELLED",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_update_to_an_existing_source_status_is_a_conflict(client, carrier_id):
    first = (
        await client.post(
            URL,
            json={"carrier_id": carrier_id, "raw_status": "A", "canonical_status": "CREATED"},
            headers=ADMIN,
        )
    ).json()
    await client.post(
        URL,
        json={"carrier_id": carrier_id, "raw_status": "B", "canonical_status": "CREATED"},
        headers=ADMIN,
    )

    response = await client.patch(f"{URL}/{first['id']}", json={"raw_status": "B"}, headers=ADMIN)

    assert response.status_code == 409
    # The conflict did not leave a broken session: listing continues to work.
    listing = await client.get(URL, params={"carrier_id": carrier_id}, headers=ADMIN)
    assert [m["raw_status"] for m in listing.json()] == ["A", "B"]


async def test_patch_and_delete_of_missing_mapping_return_404(client, db_ready):
    assert (
        await client.patch(f"{URL}/999999999", json={"canonical_status": "CREATED"}, headers=ADMIN)
    ).status_code == 404
    assert (await client.delete(f"{URL}/999999999", headers=ADMIN)).status_code == 404


async def test_patch_requires_at_least_one_field(client, db_ready):
    response = await client.patch(f"{URL}/1", json={}, headers=ADMIN)

    assert response.status_code == 422


async def test_list_reads_from_the_database_and_filters_by_carrier(client, carrier_id):
    await client.post(
        URL,
        json={"carrier_id": carrier_id, "raw_status": "ONLY", "canonical_status": "CREATED"},
        headers=ADMIN,
    )

    response = await client.get(URL, params={"carrier_id": carrier_id}, headers=ADMIN)

    assert [m["raw_status"] for m in response.json()] == ["ONLY"]
    async with AsyncSessionLocal() as session:
        assert (
            await session.scalars(select(StateMapping).where(StateMapping.carrier_id == carrier_id))
        ).all()
