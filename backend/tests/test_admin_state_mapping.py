"""Pruebas del endpoint admin de state_mapping.

- Las de seguridad no necesitan base de datos.
- Las de flujo completo usan PostgreSQL real con las migraciones ya aplicadas
  (`alembic upgrade head`); si la base no está disponible, se omiten.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.carrier import Carrier
from app.models.state_mapping import CANONICAL_STATUSES, StateMapping
from app.services.state_mapping_cache import state_mapping_cache

URL = "/api/v1/admin/state-mappings"
ADMIN = {"X-Admin-Token": "test-admin-key"}
TEST_CARRIER_NAME = "pytest-carrier"


# ---------- Seguridad (sin base de datos) ----------


def test_admin_is_disabled_when_no_key_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "")

    response = TestClient(app).get(URL, headers=ADMIN)

    assert response.status_code == 503


def test_admin_rejects_missing_or_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    client = TestClient(app)

    assert client.get(URL).status_code == 401
    assert client.get(URL, headers={"X-Admin-Token": "otra-cosa"}).status_code == 401


# ---------- Flujo completo (PostgreSQL real) ----------


@pytest.fixture
async def db_ready():
    await engine.dispose()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1 FROM state_mapping LIMIT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("PostgreSQL con migraciones aplicadas no disponible")
    yield
    await engine.dispose()  # cada test usa su propio event loop


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
        json={"carrier_id": carrier_id, "raw_status": " SHIPPED ", "canonical_status": "in_transit"},
        headers=ADMIN,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["raw_status"] == "SHIPPED"  # sin espacios
    assert body["canonical_status"] == "IN_TRANSIT"  # normalizado a mayúsculas

    # Primera consulta: llena la caché.
    first = await resolve(client, carrier_id, "SHIPPED")
    assert first.json()["canonical_status"] == "IN_TRANSIT"

    # Editar: la caché ya tenía el valor viejo, pero el cambio se ve de inmediato.
    patched = await client.patch(
        f"{URL}/{body['id']}", json={"canonical_status": "DELIVERED"}, headers=ADMIN
    )
    assert patched.status_code == 200
    assert (await resolve(client, carrier_id, "SHIPPED")).json()["canonical_status"] == "DELIVERED"

    # Borrar: deja de resolverse.
    deleted = await client.delete(f"{URL}/{body['id']}", headers=ADMIN)
    assert deleted.status_code == 204
    assert (await resolve(client, carrier_id, "SHIPPED")).status_code == 404


async def test_create_validations(client, carrier_id):
    payload = {"carrier_id": carrier_id, "raw_status": "X", "canonical_status": "DELIVERED"}
    assert (await client.post(URL, json=payload, headers=ADMIN)).status_code == 201

    duplicate = await client.post(URL, json=payload, headers=ADMIN)
    assert duplicate.status_code == 409

    unknown_carrier = await client.post(URL, json={**payload, "carrier_id": 999_999_999}, headers=ADMIN)
    assert unknown_carrier.status_code == 404

    bad_canonical = await client.post(URL, json={**payload, "canonical_status": "NOPE"}, headers=ADMIN)
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


async def test_simulated_carriers_have_full_canonical_seed(client, db_ready):
    async with AsyncSessionLocal() as session:
        counts = dict(
            (
                await session.execute(
                    select(Carrier.name, func.count(StateMapping.id))
                    .join(StateMapping, StateMapping.carrier_id == Carrier.carrier_id)
                    .where(
                        Carrier.name.in_(
                            ("SimCarrier Alpha", "SimCarrier Beta", "SimCarrier Gamma")
                        )
                    )
                    .group_by(Carrier.name)
                )
            ).all()
        )
        seeded_statuses = set(
            (
                await session.scalars(
                    select(StateMapping.canonical_status)
                    .join(Carrier, Carrier.carrier_id == StateMapping.carrier_id)
                    .where(
                        Carrier.name.in_(
                            ("SimCarrier Alpha", "SimCarrier Beta", "SimCarrier Gamma")
                        )
                    )
                    .distinct()
                )
            ).all()
        )

    assert set(counts) == {"SimCarrier Alpha", "SimCarrier Beta", "SimCarrier Gamma"}
    assert all(count >= 6 for count in counts.values())
    assert seeded_statuses == set(CANONICAL_STATUSES)


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
    # El conflicto no dejó la sesión rota: el listado sigue funcionando.
    listing = await client.get(URL, params={"carrier_id": carrier_id}, headers=ADMIN)
    assert [m["raw_status"] for m in listing.json()] == ["A", "B"]


async def test_patch_and_delete_of_missing_mapping_return_404(client, db_ready):
    assert (await client.patch(f"{URL}/999999999", json={"canonical_status": "CREATED"}, headers=ADMIN)).status_code == 404
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
        assert (await session.scalars(select(StateMapping).where(StateMapping.carrier_id == carrier_id))).all()
