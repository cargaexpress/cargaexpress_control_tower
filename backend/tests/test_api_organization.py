"""Validation tests for CargaExpress API reorganization into 5 functional groups:
A. Operational API
B. Integration API
C. Internal Process API
D. Administration API
E. Monitoring API
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


@pytest.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_openapi_schema_contains_all_5_required_groups():
    """Verify that OpenAPI / Swagger schema includes tag definitions for all 5 functional groups."""
    spec = app.openapi()
    tags = {tag["name"] for tag in spec.get("tags", [])}

    expected_groups = {
        # Group A: Operational API
        "Operational: Orders",
        "Operational: Carriers",
        "Operational: SLA & Compliance",
        "Operational: Alerts",
        "Operational: Financial",
        "Operational: Analytics",
        # Group B: Integration API
        "Integration: Webhooks",
        "Integration: Connectors",
        # Group C: Internal Process API
        "Internal Processes: Alerts",
        "Internal Processes: Financial Settlements",
        "Internal Processes: Analytics ETL",
        # Group D: Administration API
        "Administration: State Mappings",
        # Group E: Monitoring API
        "Monitoring: Health & Readiness",
    }
    assert expected_groups.issubset(tags), (
        f"Missing functional group tags: {expected_groups - tags}"
    )


@pytest.mark.asyncio
async def test_all_required_endpoints_exist_in_openapi_spec():
    """Verify all required endpoints from the 5 functional groups are mapped in OpenAPI."""
    spec = app.openapi()
    paths = spec.get("paths", {})

    # Group A: Operational API
    assert "/api/v1/orders" in paths
    assert "/api/v1/orders/{order_id}" in paths
    assert "/api/v1/orders/{order_id}/status" in paths
    assert "/api/v1/orders/{order_id}/shipping-labels" in paths
    assert "/api/v1/carriers" in paths
    assert "/api/v1/carriers/me" in paths
    assert "/api/v1/carriers/{carrier_id}" in paths
    assert "/api/v1/sla/orders/{order_id}" in paths
    assert "/api/v1/sla/at-risk" in paths
    assert "/api/v1/sla/brand/metrics" in paths
    assert "/api/v1/sla/brand/shipments" in paths
    assert "/api/v1/sla/brand/history" in paths
    assert "/api/v1/sla/carrier/metrics" in paths
    assert "/api/v1/sla/carrier/shipments" in paths
    assert "/api/v1/sla/carrier/history" in paths
    assert "/api/v1/alerts" in paths
    assert "/api/v1/alerts/{alert_id}/resolve" in paths
    assert "/api/v1/financial/penalties" in paths
    assert "/api/v1/financial/settlements/{settlement_id}" in paths
    assert "/api/v1/analytics/kpis" in paths
    assert "/api/v1/analytics/facts/shipments-sla" in paths
    assert "/api/v1/analytics/facts/penalties" in paths

    # Group B: Integration API
    assert "/api/v1/webhooks/{carrier_slug}" in paths
    assert "/api/v1/sync/type-a" in paths
    assert "/api/v1/sync/type-b" in paths
    assert "/api/v1/sync/type-c" in paths
    assert "/api/v1/sync/type-c/upload" in paths

    # Group C: Internal Process API
    assert "/api/v1/alerts/scan" in paths
    assert "/api/v1/financial/settlements/generate" in paths
    assert "/api/v1/analytics/etl/run" in paths

    # Group D: Administration API
    assert "/api/v1/admin/state-mappings" in paths
    assert "/api/v1/admin/state-mappings/resolve" in paths
    assert "/api/v1/admin/carrier-state-mappings/{carrier_id}" in paths

    # Group E: Monitoring API
    assert "/api/v1/health" in paths
    assert "/api/v1/ready" in paths


@pytest.mark.asyncio
async def test_internal_process_endpoints_reject_unauthenticated_requests(api_client):
    """Ensure internal execution endpoints cannot be triggered without valid credentials."""
    # 1. Alert scanning
    res_scan = await api_client.post("/api/v1/alerts/scan")
    assert res_scan.status_code == 401

    # 2. Financial settlement generation
    res_settle = await api_client.post(
        "/api/v1/financial/settlements/generate",
        json={"carrier_id": 1, "year": 2026, "month": 10, "half": 1},
    )
    assert res_settle.status_code == 401

    # 3. Analytics ETL execution
    res_etl = await api_client.post("/api/v1/analytics/etl/run")
    assert res_etl.status_code == 401


@pytest.mark.asyncio
async def test_internal_process_endpoints_reject_tenant_brand_and_carrier_keys(
    api_client, monkeypatch
):
    """Ensure tenant brand and carrier API keys CANNOT execute controlled internal operations."""
    monkeypatch.setattr(settings, "admin_api_key", "admin_secret_key_32_characters_min")
    monkeypatch.setattr(settings, "api_key", "system_internal_key_32_chars_min")
    monkeypatch.setattr(settings, "brand_api_keys", {"brand_tenant_key_32_characters_1": 1})
    monkeypatch.setattr(settings, "carrier_api_keys", {"carrier_tenant_key_32_characters": 1})

    brand_headers = {"X-API-Key": "brand_tenant_key_32_characters_1"}
    carrier_headers = {"X-API-Key": "carrier_tenant_key_32_characters"}

    for headers in (brand_headers, carrier_headers):
        res_scan = await api_client.post("/api/v1/alerts/scan", headers=headers)
        assert res_scan.status_code == 401, f"Expected 401 for headers: {headers}"

        res_settle = await api_client.post(
            "/api/v1/financial/settlements/generate",
            json={"carrier_id": 1, "year": 2026, "month": 10, "half": 1},
            headers=headers,
        )
        assert res_settle.status_code == 401, f"Expected 401 for headers: {headers}"

        res_etl = await api_client.post("/api/v1/analytics/etl/run", headers=headers)
        assert res_etl.status_code == 401, f"Expected 401 for headers: {headers}"


@pytest.mark.asyncio
async def test_internal_process_endpoints_accept_internal_admin_token(api_client, monkeypatch):
    """Ensure administrators with X-Admin-Token can trigger controlled operations."""
    admin_token = "admin_secret_key_32_characters_min"
    monkeypatch.setattr(settings, "admin_api_key", admin_token)

    admin_headers = {"X-Admin-Token": admin_token}

    # Verify authorization check passes (status code is not 401)
    res_scan = await api_client.post("/api/v1/alerts/scan", headers=admin_headers)
    assert res_scan.status_code in {200, 201}


@pytest.mark.asyncio
async def test_internal_process_endpoints_accept_internal_system_api_key(api_client, monkeypatch):
    """Ensure internal orchestration systems (Airflow/Celery) with master API key can trigger operations."""
    system_key = "system_internal_key_32_chars_min"
    monkeypatch.setattr(settings, "api_key", system_key)
    monkeypatch.setattr(settings, "admin_api_key", "admin_secret_key_32_characters_min")

    system_headers = {"X-API-Key": system_key}

    res_scan = await api_client.post("/api/v1/alerts/scan", headers=system_headers)
    assert res_scan.status_code in {200, 201}


@pytest.mark.asyncio
async def test_monitoring_endpoints_health_and_ready(api_client):
    """Verify monitoring endpoints GET /api/v1/health and GET /api/v1/ready return HTTP 200."""
    res_health = await api_client.get("/api/v1/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    res_ready = await api_client.get("/api/v1/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ok"
    assert res_ready.json()["database"] == "up"
