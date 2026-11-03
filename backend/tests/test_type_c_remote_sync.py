import httpx
import pytest

from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.order_line import OrderLine
from app.models.order_recipient import OrderRecipient
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.state_mapping import StateMapping
from app.services.state_mapping_cache import state_mapping_cache
from app.services.type_c_connector import TypeCConnectorService


@pytest.fixture
async def setup_carrier_and_order(db_session):
    brand = Brand(brand_id=1, name="Test Brand", tier="standard", is_active=True)
    dc = DistributionCenter(dc_id=1, code="DC01", name="Main DC", city="Bogota", country_code="CO")
    st = ShipmentType(shipment_type_code="STD", description="Standard Delivery")
    carrier = Carrier(
        carrier_id=10,
        name="TransExpress Logistics",
        integration_type="file",
        status="active",
    )
    db_session.add_all([brand, dc, st, carrier])
    await db_session.commit()

    mapping = StateMapping(
        id=101,
        carrier_id=carrier.carrier_id,
        raw_status="IN_DEPOT",
        canonical_status="IN_TRANSIT",
    )
    db_session.add(mapping)
    await db_session.commit()
    state_mapping_cache.invalidate()

    order = Order(
        order_id=10,
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=st.shipment_type_code,
        brand_order_ref="ORD-TYPEC-01",
        destination_country="CO",
        freight_value=10000.0,
        status="CREATED",
        order_lines=[
            OrderLine(order_line_id=10, order_id=10, line_number=1, sku="SKU-C", quantity_ordered=1)
        ],
        recipient=OrderRecipient(
            order_id=10,
            full_name="Cliente C",
            address_line="Calle 1 # 2-3",
            city="Bogota",
        ),
    )
    db_session.add(order)
    await db_session.commit()

    label = ShippingLabel(
        label_id=10,
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TEL-12345",
        status="CREATED",
    )
    db_session.add(label)
    await db_session.commit()
    return carrier, label


@pytest.mark.asyncio
async def test_sync_from_carrier_endpoints_success(db_session, setup_carrier_and_order):
    carrier, label = setup_carrier_and_order

    csv_content = (
        b"waybill_no,status_code,status_description,event_time,hub_city\n"
        b"TEL-12345,IN_DEPOT,In central depot,2026-11-03T08:00:00Z,Bogota\n"
    )

    async def mock_handler(request: httpx.Request):
        if request.url.path.endswith("/download"):
            return httpx.Response(
                200,
                content=csv_content,
                headers={"Content-Disposition": 'attachment; filename="batch_carrier_1.csv"'},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = TypeCConnectorService(client=mock_client)
        results = await service.sync_from_carrier_endpoints(
            db=db_session,
            carrier_urls={"TransExpress Logistics": "http://mock-carrier:8005"},
        )

        assert len(results) == 1
        res = results[0]
        assert res.status == "completed"
        assert res.filename == "batch_carrier_1.csv"
        assert res.valid_rows_processed == 1
        assert res.errors == 0

        # Verify database update
        await db_session.refresh(label)
        assert label.status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_sync_from_carrier_endpoints_retries_on_429(db_session, setup_carrier_and_order):
    carrier, label = setup_carrier_and_order
    attempts = 0

    csv_content = (
        b"waybill_no,status_code,status_description,event_time,hub_city\n"
        b"TEL-12345,IN_DEPOT,In central depot,2026-11-03T08:00:00Z,Bogota\n"
    )

    async def mock_handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(
            200,
            content=csv_content,
            headers={"Content-Disposition": 'attachment; filename="retry_batch.csv"'},
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = TypeCConnectorService(
            client=mock_client,
            max_retries=3,
            base_delay_seconds=0.01,
            sleep_fn=lambda _: None,
        )
        results = await service.sync_from_carrier_endpoints(
            db=db_session,
            carrier_urls={"TransExpress Logistics": "http://mock-carrier:8005"},
        )

        assert len(results) == 1
        assert results[0].status == "completed"
        assert attempts == 2


@pytest.mark.asyncio
async def test_sync_from_minio_s3_success(db_session, setup_carrier_and_order):
    carrier, label = setup_carrier_and_order

    s3_xml_list = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        b"  <Name>type-c-carriers</Name>"
        b"  <Contents>"
        b"    <Key>batches/carrier_1_s3.csv</Key>"
        b"    <Size>123</Size>"
        b"  </Contents>"
        b"</ListBucketResult>"
    )

    csv_content = (
        b"waybill_no,status_code,status_description,event_time,hub_city\n"
        b"TEL-12345,IN_DEPOT,In central depot,2026-11-03T08:00:00Z,Bogota\n"
    )

    async def mock_handler(request: httpx.Request):
        if request.url.path == "/type-c-carriers":
            return httpx.Response(200, content=s3_xml_list)
        elif request.url.path == "/type-c-carriers/batches/carrier_1_s3.csv":
            return httpx.Response(200, content=csv_content)
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        service = TypeCConnectorService(client=mock_client)
        results = await service.sync_from_minio_s3(
            db=db_session,
            endpoint="http://mock-minio:9000",
            bucket="type-c-carriers",
        )

        assert len(results) == 1
        assert results[0].status == "completed"
        assert results[0].filename == "carrier_1_s3.csv"
        assert results[0].valid_rows_processed == 1


@pytest.mark.asyncio
async def test_api_trigger_type_c_sync(client, db_session, setup_carrier_and_order, monkeypatch):
    async def mock_sync_all(self, db):
        from app.services.type_c_connector import FileProcessingResult

        return [
            FileProcessingResult(
                filename="carrier_1_test.csv",
                carrier_name="TransExpress Logistics",
                file_hash="hash123",
                status="completed",
                valid_rows_processed=5,
            )
        ]

    monkeypatch.setattr(TypeCConnectorService, "sync_all_sources", mock_sync_all)

    resp = await client.post("/api/v1/sync/type-c/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["total_files_evaluated"] == 1
    assert data["results"][0]["filename"] == "carrier_1_test.csv"
