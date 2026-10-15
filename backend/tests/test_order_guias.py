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
    """Crea los datos maestros mínimos necesarios para pedidos y transportadoras."""
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
    """Helper para crear un pedido completo en base de datos."""
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
async def test_post_guia_success(client, db_session):
    """Registrar exitosamente una guía en un pedido existente (retorna 201 y persiste la relación)."""
    brand_a, _, dc, st, carrier, _ = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code)

    payload = {
        "tracking_number": "TRK-001-ALPHA",
        "carrier_id": carrier.carrier_id,
        "weight_kg": 2.50,
        "status": "CREADO",
    }

    response = await client.post(f"/api/v1/pedidos/{order.order_id}/guias", json=payload)

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
async def test_post_multiple_guias_split_order(client, db_session):
    """Registrar dos o más guías para el mismo pedido (escenario split order para soportar CA-03)."""
    brand_a, _, dc, st, carrier_1, carrier_2 = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="SPLIT-ORDER-99")

    # Guía 1 (Bulto 1 / Transportadora 1)
    res_1 = await client.post(
        f"/api/v1/pedidos/{order.order_id}/guias",
        json={"tracking_number": "SPLIT-TRK-01", "carrier_id": carrier_1.carrier_id, "weight_kg": 1.25},
    )
    assert res_1.status_code == 201

    # Guía 2 (Bulto 2 / Transportadora 2)
    res_2 = await client.post(
        f"/api/v1/pedidos/{order.order_id}/guias",
        json={"tracking_number": "SPLIT-TRK-02", "carrier_id": carrier_2.carrier_id, "weight_kg": 3.75},
    )
    assert res_2.status_code == 201

    # Verificar que el pedido contenga ambas guías
    list_res = await client.get(f"/api/v1/pedidos/{order.order_id}/guias")
    assert list_res.status_code == 200
    guias = list_res.json()
    assert len(guias) == 2
    tracking_numbers = [g["tracking_number"] for g in guias]
    assert "SPLIT-TRK-01" in tracking_numbers
    assert "SPLIT-TRK-02" in tracking_numbers


@pytest.mark.asyncio
async def test_post_guia_pedido_not_found(client, db_session):
    """Intentar asociar una guía a un pedido con ID inexistente (retorna 404)."""
    _, _, _, _, carrier, _ = await _seed_test_context(db_session)

    payload = {
        "tracking_number": "TRK-NON-EXISTENT",
        "carrier_id": carrier.carrier_id,
        "weight_kg": 1.0,
    }

    response = await client.post("/api/v1/pedidos/999999/guias", json=payload)
    assert response.status_code == 404
    assert "order" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_guias_success(client, db_session):
    """Consultar las guías asociadas a un pedido y comprobar que solo se retornen las guías de ese ID específico."""
    brand_a, _, dc, st, carrier, _ = await _seed_test_context(db_session)

    order_1 = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="ORD-1")
    order_2 = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="ORD-2")

    # Guía para orden 1
    await client.post(
        f"/api/v1/pedidos/{order_1.order_id}/guias",
        json={"tracking_number": "TRK-ORDER-1", "carrier_id": carrier.carrier_id},
    )

    # Guía para orden 2
    await client.post(
        f"/api/v1/pedidos/{order_2.order_id}/guias",
        json={"tracking_number": "TRK-ORDER-2", "carrier_id": carrier.carrier_id},
    )

    # Consulta para orden 1: debe devolver únicamente la guía de orden 1
    response = await client.get(f"/api/v1/pedidos/{order_1.order_id}/guias")
    assert response.status_code == 200
    guias = response.json()
    assert len(guias) == 1
    assert guias[0]["tracking_number"] == "TRK-ORDER-1"
    assert guias[0]["order_id"] == order_1.order_id


@pytest.mark.asyncio
async def test_get_guias_pedido_not_found(client):
    """Consultar guías de un pedido inexistente (retorna 404)."""
    response = await client.get("/api/v1/pedidos/999999/guias")
    assert response.status_code == 404
    assert "order" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tenant_isolation_forbidden(client, db_session):
    """Intentar registrar o consultar guías de un pedido perteneciente a otra marca (retorna 403)."""
    brand_a, brand_b, dc, st, carrier, _ = await _seed_test_context(db_session)
    order_a = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code, ref="ORD-BRAND-A")

    # Intentar crear guía en pedido de Marca A usando contexto de Marca B
    headers_brand_b = {"X-Brand-Id": str(brand_b.brand_id)}
    post_res = await client.post(
        f"/api/v1/pedidos/{order_a.order_id}/guias",
        json={"tracking_number": "TRK-ISOLATION-TEST", "carrier_id": carrier.carrier_id},
        headers=headers_brand_b,
    )
    assert post_res.status_code == 403
    assert "no pertenece a la marca" in post_res.json()["detail"]

    # Crear la guía bajo el contexto legítimo de Marca A
    headers_brand_a = {"X-Brand-Id": str(brand_a.brand_id)}
    valid_post = await client.post(
        f"/api/v1/pedidos/{order_a.order_id}/guias",
        json={"tracking_number": "TRK-ISOLATION-TEST", "carrier_id": carrier.carrier_id},
        headers=headers_brand_a,
    )
    assert valid_post.status_code == 201

    # Intentar consultar guías del pedido de Marca A usando contexto de Marca B (debe responder 403)
    get_res = await client.get(
        f"/api/v1/pedidos/{order_a.order_id}/guias",
        headers=headers_brand_b,
    )
    assert get_res.status_code == 403
    assert "no pertenece a la marca" in get_res.json()["detail"]


@pytest.mark.asyncio
async def test_post_guia_duplicate_tracking_number_returns_409(client, db_session):
    """Validar que un número de tracking ya asignado no pueda reutilizarse (409 Conflict)."""
    brand_a, _, dc, st, carrier, _ = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code)

    payload = {"tracking_number": "TRK-DUP-001", "carrier_id": carrier.carrier_id}

    res_1 = await client.post(f"/api/v1/pedidos/{order.order_id}/guias", json=payload)
    assert res_1.status_code == 201

    res_2 = await client.post(f"/api/v1/pedidos/{order.order_id}/guias", json=payload)
    assert res_2.status_code == 409
    assert "already registered" in res_2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_guia_carrier_not_found(client, db_session):
    """Intentar registrar una guía con una transportadora inexistente (retorna 404)."""
    brand_a, _, dc, st, _, _ = await _seed_test_context(db_session)
    order = await _create_test_order(db_session, brand_a.brand_id, dc.dc_id, st.shipment_type_code)

    payload = {"tracking_number": "TRK-NO-CARRIER", "carrier_id": 999999}

    response = await client.post(f"/api/v1/pedidos/{order.order_id}/guias", json=payload)
    assert response.status_code == 404
    assert "carrier" in response.json()["detail"].lower()
