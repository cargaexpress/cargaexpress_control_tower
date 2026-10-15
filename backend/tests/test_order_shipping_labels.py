from decimal import Decimal
import pytest
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.order_line import OrderLine
from app.models.order_recipient import OrderRecipient
from app.models.shipment_type import ShipmentType


async def _seed_test_context(db_session):
    """Create minimal reference master data for orders and carriers."""
    brand_a = Brand(name="Marca Alfa", tier="standard", is_active=True)
    brand_b = Brand(name="Marca Beta", tier="premium", is_active=True)
    dc = DistributionCenter(code="DC01", name="Bogota DC", city="Bogota", country_code="CO")
    shipment_type = ShipmentType(shipment_type_code="STD", description="Standard shipment")
    carrier_1 = Carrier(name="Servientrega", integration_type="api", status="active")
    carrier_2 = Carrier(name="Coordinadora", integration_type="webhook", status="active")

    db_session.add_all([brand_a, brand_b, dc, shipment_type, carrier_1, carrier_2])
    await db_session.commit()
    for entity in (brand_a, brand_b, dc, shipment_type, carrier_1, carrier_2):
        await db_session.refresh(entity)

    return brand_a, brand_b, dc, shipment_type, carrier_1, carrier_2


async def _create_test_order(db_session, brand_id, dc_id, shipment_type_code, ref="ORD-001"):
    """Helper to create a full order in the database."""
    order = Order(
        brand_id=brand_id,
        dc_id=dc_id,
        shipment_type_code=shipment_type_code,
        brand_order_ref=ref,
        destination_country="CO",
        destination_region="Cundinamarca",
        freight_value=Decimal("25000.00"),
        status="CREADO",
        order_lines=[
            OrderLine(line_number=1, sku="SKU-100", quantity_ordered=2),
        ],
        recipient=OrderRecipient(
            full_name="Carlos Gomez",
            email="carlos@example.com",
            phone="3101234567",
            address_line="Carrera 7 # 45-10",
            city="Bogota",
        ),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    return order


@pytest.mark.asyncio
async def test_create_shipping_label_success(client, db_session):
    """Successfully register a shipping label on an existing order (returns 201 and persists relationship)."""
    brand_a, _, dc, st, carrier, _ = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code)

    payload = {
        "tracking_number": "TRK-001-ALPHA",
        "carrier_id": carrier.carrier_id,
        "weight_kg": 2.50,
        "status": "CREADO",
    }

    response = await client.post(f"/api/v1/orders/{order.order_id}/shipping-labels", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["tracking_number"] == "TRK-001-ALPHA"
    assert body["order_id"] == order.order_id
    assert body["carrier_id"] == carrier.carrier_id
    assert body["status"] == "CREADO"
    assert float(body["weight_kg"]) == 2.50
    assert "label_id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_create_multiple_shipping_labels_split_order(client, db_session):
    """Register two or more shipping labels for the same order (split order scenario for CA-03)."""
    brand_a, _, dc, st, carrier_1, carrier_2 = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="SPLIT-ORDER-99")

    # Label 1 (Package 1 / Carrier 1)
    res_1 = await client.post(
        f"/api/v1/orders/{order.order_id}/shipping-labels",
        json={"tracking_number": "SPLIT-TRK-01", "carrier_id": carrier_1.carrier_id, "weight_kg": 1.25},
    )
    assert res_1.status_code == 201

    # Label 2 (Package 2 / Carrier 2)
    res_2 = await client.post(
        f"/api/v1/orders/{order.order_id}/shipping-labels",
        json={"tracking_number": "SPLIT-TRK-02", "carrier_id": carrier_2.carrier_id, "weight_kg": 3.75},
    )
    assert res_2.status_code == 201

    # Verify the order contains both shipping labels
    list_res = await client.get(f"/api/v1/orders/{order.order_id}/shipping-labels")
    assert list_res.status_code == 200
    shipping_labels = list_res.json()
    assert len(shipping_labels) == 2
    tracking_numbers = [label["tracking_number"] for label in shipping_labels]
    assert "SPLIT-TRK-01" in tracking_numbers
    assert "SPLIT-TRK-02" in tracking_numbers


@pytest.mark.asyncio
async def test_create_shipping_label_order_not_found(client, db_session):
    """Attempt to associate a shipping label with a nonexistent order ID (returns 404)."""
    _, _, _, _, carrier, _ = await _seed_test_context(db_session)

    payload = {
        "tracking_number": "TRK-NON-EXISTENT",
        "carrier_id": carrier.carrier_id,
        "weight_kg": 1.0,
    }

    response = await client.post("/api/v1/orders/999999/shipping-labels", json=payload)
    assert response.status_code == 404
    assert "order" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_shipping_labels_success(client, db_session):
    """Query shipping labels associated with an order and ensure only labels for that order ID are returned."""
    brand_a, _, dc, st, carrier, _ = await _seed_test_context(db_session)

    order_1 = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="ORD-1")
    order_2 = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="ORD-2")

    # Label for order 1
    await client.post(
        f"/api/v1/orders/{order_1.order_id}/shipping-labels",
        json={"tracking_number": "TRK-ORDER-1", "carrier_id": carrier.carrier_id},
    )

    # Label for order 2
    await client.post(
        f"/api/v1/orders/{order_2.order_id}/shipping-labels",
        json={"tracking_number": "TRK-ORDER-2", "carrier_id": carrier.carrier_id},
    )

    # Query for order 1: should return only the shipping label for order 1
    response = await client.get(f"/api/v1/orders/{order_1.order_id}/shipping-labels")
    assert response.status_code == 200
    shipping_labels = response.json()
    assert len(shipping_labels) == 1
    assert shipping_labels[0]["tracking_number"] == "TRK-ORDER-1"
    assert shipping_labels[0]["order_id"] == order_1.order_id


@pytest.mark.asyncio
async def test_get_shipping_labels_order_not_found(client):
    """Query shipping labels of a nonexistent order (returns 404)."""
    response = await client.get("/api/v1/orders/999999/shipping-labels")
    assert response.status_code == 404
    assert "order" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tenant_isolation_forbidden(client, db_session):
    """Attempt to register or query shipping labels of an order belonging to another brand (returns 403)."""
    brand_a, brand_b, dc, st, carrier, _ = await _seed_test_context(db_session)
    order_a = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="ORD-BRAND-A")

    # Attempt to create label in Brand A's order using Brand B's context
    headers_brand_b = {"X-Brand-Id": str(brand_b.brand_id)}
    post_res = await client.post(
        f"/api/v1/orders/{order_a.order_id}/shipping-labels",
        json={"tracking_number": "TRK-ISOLATION-TEST", "carrier_id": carrier.carrier_id},
        headers=headers_brand_b,
    )
    assert post_res.status_code == 403
    assert "does not belong to brand" in post_res.json()["detail"].lower()

    # Create label under legitimate Brand A context
    headers_brand_a = {"X-Brand-Id": str(brand_a.brand_id)}
    valid_post = await client.post(
        f"/api/v1/orders/{order_a.order_id}/shipping-labels",
        json={"tracking_number": "TRK-ISOLATION-TEST", "carrier_id": carrier.carrier_id},
        headers=headers_brand_a,
    )
    assert valid_post.status_code == 201

    # Attempt to query labels of Brand A's order using Brand B's context (returns 403)
    get_res = await client.get(
        f"/api/v1/orders/{order_a.order_id}/shipping-labels",
        headers=headers_brand_b,
    )
    assert get_res.status_code == 403
    assert "does not belong to brand" in get_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_shipping_label_duplicate_tracking_number_returns_409(client, db_session):
    """Validate that an already assigned tracking number cannot be reused (409 Conflict)."""
    brand_a, _, dc, st, carrier, _ = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code)

    payload = {"tracking_number": "TRK-DUP-001", "carrier_id": carrier.carrier_id}

    res_1 = await client.post(f"/api/v1/orders/{order.order_id}/shipping-labels", json=payload)
    assert res_1.status_code == 201

    res_2 = await client.post(f"/api/v1/orders/{order.order_id}/shipping-labels", json=payload)
    assert res_2.status_code == 409
    assert "already registered" in res_2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_shipping_label_carrier_not_found(client, db_session):
    """Attempt to register a shipping label with a nonexistent carrier (returns 404)."""
    brand_a, _, dc, st, _, _ = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code)

    payload = {"tracking_number": "TRK-NO-CARRIER", "carrier_id": 999999}

    response = await client.post(f"/api/v1/orders/{order.order_id}/shipping-labels", json=payload)
    assert response.status_code == 404
    assert "carrier" in response.json()["detail"].lower()
