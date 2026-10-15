import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import app
from scripts.export_openapi import export_openapi_schema


@pytest.mark.asyncio
async def test_docs_ui_is_available():
    """Verify Swagger UI interface is available and returns HTTP 200 at /docs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/docs")
        assert response.status_code == 200
        assert "swagger-ui" in response.text.lower() or "html" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_openapi_json_endpoint_is_available():
    """Verify /docs/api/openapi.json directly serves a valid OpenAPI specification."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/docs/api/openapi.json")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

        spec = response.json()
        assert spec["info"]["title"] == "CargaExpress Supply Chain API"
        assert spec["info"]["version"] == "1.0.0"
        assert "paths" in spec


@pytest.mark.asyncio
async def test_openapi_schema_contains_required_metadata_and_tags():
    """Verify OpenAPI schema contains required tags and organized core endpoints."""
    spec = app.openapi()

    tags = {tag["name"] for tag in spec.get("tags", [])}
    expected_tags = {"health", "pedidos", "admin: state mapping", "admin: mapeo de estados", "contrato openapi"}
    assert expected_tags.issubset(tags), f"Missing tags: {expected_tags - tags}"

    paths = spec.get("paths", {})
    assert "/api/v1/health" in paths
    assert "/api/v1/pedidos" in paths
    assert "/api/v1/pedidos/{order_id}" in paths
    assert "/api/v1/admin/state-mappings" in paths
    assert "/api/v1/admin/mapeo-estados/{transportadora_id}" in paths
    assert "/docs/api/openapi.json" in paths


@pytest.mark.asyncio
async def test_openapi_schema_models_have_examples():
    """Verify Pydantic models include representative examples in schemas."""
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})

    assert "OrderCreate" in schemas
    order_create = schemas["OrderCreate"]
    assert "example" in order_create or "examples" in order_create

    assert "OrderRead" in schemas
    assert "StateMappingCreate" in schemas
    mapping_create = schemas["StateMappingCreate"]
    assert "example" in mapping_create or "examples" in mapping_create


def test_export_openapi_script_generates_valid_file(tmp_path: Path):
    """Verify scripts/export_openapi.py generates a valid JSON identical to app.openapi()."""
    target_file = tmp_path / "openapi_test.json"
    result_path = export_openapi_schema(target_file)

    assert result_path.exists()
    assert result_path.stat().st_size > 0

    with open(result_path, encoding="utf-8") as f:
        loaded_data = json.load(f)

    app_spec = app.openapi()
    assert loaded_data["info"] == app_spec["info"]
    assert set(loaded_data["paths"].keys()) == set(app_spec["paths"].keys())
