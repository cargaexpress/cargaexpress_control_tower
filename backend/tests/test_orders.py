from app.config import settings
from app.models.brand import Brand
from app.models.distribution_center import DistributionCenter
from app.models.shipment_type import ShipmentType


# Seed only required references so tests exercise the real API validation path.
async def _seed_reference_data(db_session):
    brand = Brand(name="Acme", tier="standard", is_active=True)
    dc = DistributionCenter(code="DC01", name="Bogota DC", city="Bogota", country_code="CO")
    shipment_type = ShipmentType(shipment_type_code="STD", description="Standard shipment")

    db_session.add_all([brand, dc, shipment_type])
    await db_session.commit()
    await db_session.refresh(brand)
    await db_session.refresh(dc)
    return brand, dc, shipment_type


def _order_payload(brand_id, dc_id, shipment_type_code):
    return {
        "brand_id": brand_id,
        "dc_id": dc_id,
        "shipment_type_code": shipment_type_code,
        "brand_order_ref": "ACME-0001",
        "destination_country": "CO",
        "destination_region": "Atlantico",
        "freight_value": "45000.00",
        "status": "created",
        "order_lines": [
            {"sku": "SKU-1", "description": "Item 1", "quantity_ordered": 2},
            {"sku": "SKU-2", "description": None, "quantity_ordered": 1},
        ],
        "recipient": {
            "full_name": "Juan Perez",
            "email": "juan@example.com",
            "phone": "3001234567",
            "address_line": "Calle 10 # 20-30",
            "city": "Barranquilla",
        },
    }


async def test_create_order_success(client, db_session):
    brand, dc, shipment_type = await _seed_reference_data(db_session)
    payload = _order_payload(brand.brand_id, dc.dc_id, shipment_type.shipment_type_code)

    response = await client.post("/api/v1/orders", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["brand_id"] == brand.brand_id
    assert len(body["order_lines"]) == 2
    assert body["order_lines"][0]["line_number"] == 1
    assert body["order_lines"][1]["line_number"] == 2
    assert body["recipient"]["full_name"] == "Juan Perez"


async def test_create_order_uses_authenticated_brand_not_body_brand(client, db_session):
    brand, dc, shipment_type = await _seed_reference_data(db_session)
    payload = _order_payload(999999, dc.dc_id, shipment_type.shipment_type_code)

    response = await client.post("/api/v1/orders", json=payload)

    assert response.status_code == 201
    assert response.json()["brand_id"] == brand.brand_id


async def test_duplicate_order_reference_conflicts_only_within_brand(
    client, db_session, monkeypatch
):
    brand_a = Brand(name="Acme", tier="standard", is_active=True)
    brand_b = Brand(name="Other", tier="standard", is_active=True)
    dc = DistributionCenter(code="DC01", name="Bogota DC", city="Bogota", country_code="CO")
    shipment_type = ShipmentType(shipment_type_code="STD", description="Standard shipment")
    db_session.add_all([brand_a, brand_b, dc, shipment_type])
    await db_session.commit()
    await db_session.refresh(brand_a)
    await db_session.refresh(brand_b)
    await db_session.refresh(dc)

    api_key_a = client.headers["X-API-Key"]
    api_key_b = "other-brand-test-key"
    monkeypatch.setattr(
        settings,
        "brand_api_keys",
        {api_key_a: brand_a.brand_id, api_key_b: brand_b.brand_id},
    )

    payload = _order_payload(brand_a.brand_id, dc.dc_id, shipment_type.shipment_type_code)
    created_a = await client.post("/api/v1/orders", json=payload)
    duplicate_a = await client.post("/api/v1/orders", json=payload)
    created_b = await client.post(
        "/api/v1/orders",
        json={**payload, "brand_id": brand_b.brand_id},
        headers={"X-API-Key": api_key_b},
    )

    assert created_a.status_code == 201
    assert duplicate_a.status_code == 409
    assert created_b.status_code == 201
    assert created_b.json()["brand_id"] == brand_b.brand_id


async def test_get_order_by_id(client, db_session):
    brand, dc, shipment_type = await _seed_reference_data(db_session)
    payload = _order_payload(brand.brand_id, dc.dc_id, shipment_type.shipment_type_code)
    created = await client.post("/api/v1/orders", json=payload)
    order_id = created.json()["order_id"]

    response = await client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    assert response.json()["order_id"] == order_id


async def test_get_order_not_found(client):
    response = await client.get("/api/v1/orders/999999")

    assert response.status_code == 404


async def test_list_orders_paginated(client, db_session):
    brand, dc, shipment_type = await _seed_reference_data(db_session)
    payload = _order_payload(brand.brand_id, dc.dc_id, shipment_type.shipment_type_code)
    await client.post("/api/v1/orders", json=payload)
    await client.post(
        "/api/v1/orders",
        json={**payload, "brand_order_ref": "ACME-0002"},
    )

    response = await client.get("/api/v1/orders", params={"skip": 0, "limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["skip"] == 0
    assert body["limit"] == 1


async def test_update_order_status(client, db_session):
    brand, dc, shipment_type = await _seed_reference_data(db_session)
    payload = _order_payload(brand.brand_id, dc.dc_id, shipment_type.shipment_type_code)
    created = await client.post("/api/v1/orders", json=payload)
    order_id = created.json()["order_id"]

    response = await client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "PICKED_UP"})

    assert response.status_code == 200
    assert response.json()["status"] == "PICKED_UP"


async def test_update_order_status_not_found(client):
    response = await client.patch("/api/v1/orders/999999/status", json={"status": "PICKED_UP"})

    assert response.status_code == 404
