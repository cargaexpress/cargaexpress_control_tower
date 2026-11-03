import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.carrier import Carrier


@pytest.mark.asyncio
async def test_carrier_endpoints_listing_and_self_profile(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    # 1. Seed two carriers
    c1 = Carrier(name="Carrier Uno", integration_type="webhook", status="active")
    c2 = Carrier(name="Carrier Dos", integration_type="rest_api", status="active")
    db_session.add_all([c1, c2])
    await db_session.commit()
    await db_session.refresh(c1)
    await db_session.refresh(c2)

    api_key_global = "global_api_key_for_testing_12345678"
    api_key_carrier_1 = "carrier_1_secret_key_32_characters_123"
    api_key_carrier_2 = "carrier_2_secret_key_32_characters_456"

    monkeypatch.setattr(settings, "api_key", api_key_global)
    monkeypatch.setattr(
        settings,
        "carrier_api_keys",
        {
            api_key_carrier_1: c1.carrier_id,
            api_key_carrier_2: c2.carrier_id,
        },
    )

    # 2. Control Tower lists all carriers
    resp = await client.get("/api/v1/carriers", headers={"X-API-Key": api_key_global})
    assert resp.status_code == 200
    carriers = resp.json()
    assert len(carriers) >= 2
    carrier_ids = [c["carrier_id"] for c in carriers]
    assert c1.carrier_id in carrier_ids
    assert c2.carrier_id in carrier_ids

    # 3. Carrier 1 checks its own profile via /api/v1/carriers/me
    resp_me1 = await client.get("/api/v1/carriers/me", headers={"X-API-Key": api_key_carrier_1})
    assert resp_me1.status_code == 200
    data_me1 = resp_me1.json()
    assert data_me1["carrier_id"] == c1.carrier_id
    assert data_me1["name"] == "Carrier Uno"
    assert data_me1["integration_type"] == "webhook"

    # 4. Carrier 2 checks its own profile via /api/v1/carriers/me
    resp_me2 = await client.get("/api/v1/carriers/me", headers={"X-API-Key": api_key_carrier_2})
    assert resp_me2.status_code == 200
    data_me2 = resp_me2.json()
    assert data_me2["carrier_id"] == c2.carrier_id
    assert data_me2["name"] == "Carrier Dos"
    assert data_me2["integration_type"] == "rest_api"

    # 5. Carrier 1 checks its own SLA metrics
    resp_metrics1 = await client.get("/api/v1/sla/carrier/metrics", headers={"X-API-Key": api_key_carrier_1})
    assert resp_metrics1.status_code == 200
    data_metrics1 = resp_metrics1.json()
    assert data_metrics1["carrier_id"] == c1.carrier_id
    assert data_metrics1["carrier_name"] == "Carrier Uno"
    assert "total_shipments" in data_metrics1
    assert "compliance_rate_pct" in data_metrics1
