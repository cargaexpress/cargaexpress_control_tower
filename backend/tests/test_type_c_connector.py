import io
from decimal import Decimal

import openpyxl
import pytest
from sqlalchemy import select

from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.order_line import OrderLine
from app.models.order_recipient import OrderRecipient
from app.models.processed_file import ProcessedFile
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.state_mapping import StateMapping
from app.models.tracking_anomaly import TrackingAnomaly
from app.services.state_mapping_cache import state_mapping_cache
from app.services.type_c_connector import TypeCConnectorService


async def _seed_test_carrier_c(db_session):
    """Seed reference data for Type C file tests."""
    brand = Brand(brand_id=1, name="Brand C", tier="standard", is_active=True)
    dc = DistributionCenter(dc_id=1, code="DC01", name="Main DC", city="Bogota", country_code="CO")
    shipment_type = ShipmentType(shipment_type_code="STD", description="Standard Delivery")
    carrier = Carrier(
        carrier_id=20, name="TransExpress Logistics", integration_type="file", status="active"
    )

    db_session.add_all([brand, dc, shipment_type, carrier])
    await db_session.commit()

    mappings = [
        StateMapping(
            id=201,
            carrier_id=carrier.carrier_id,
            raw_status="DISPATCHED",
            canonical_status="PICKED_UP",
        ),
        StateMapping(
            id=202,
            carrier_id=carrier.carrier_id,
            raw_status="IN_DEPOT",
            canonical_status="IN_TRANSIT",
        ),
        StateMapping(
            id=203,
            carrier_id=carrier.carrier_id,
            raw_status="DELIVERED",
            canonical_status="DELIVERED",
        ),
    ]
    db_session.add_all(mappings)
    await db_session.commit()
    state_mapping_cache.invalidate()

    order = Order(
        order_id=20,
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=shipment_type.shipment_type_code,
        brand_order_ref="ORD-TYPEC-001",
        destination_country="CO",
        destination_region="Valle",
        freight_value=Decimal("18000.00"),
        status="CREATED",
        order_lines=[
            OrderLine(order_line_id=20, order_id=20, line_number=1, sku="SKU-C", quantity_ordered=1)
        ],
        recipient=OrderRecipient(
            order_id=20,
            full_name="Cliente C",
            address_line="Av 6N # 20-30",
            city="Cali",
        ),
    )
    db_session.add(order)
    await db_session.commit()

    label_1 = ShippingLabel(
        label_id=20,
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-TYPEC-001",
        status="CREATED",
    )
    label_2 = ShippingLabel(
        label_id=21,
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-TYPEC-002",
        status="CREATED",
    )
    label_delivered = ShippingLabel(
        label_id=22,
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number="TRK-TYPEC-DELIVERED",
        status="DELIVERED",
    )

    db_session.add_all([label_1, label_2, label_delivered])
    await db_session.commit()

    return {
        "carrier": carrier,
        "label_1": label_1,
        "label_2": label_2,
        "label_delivered": label_delivered,
    }


@pytest.mark.asyncio
async def test_type_c_csv_reader_cleans_defects_and_normalizes(db_session):
    """Subtask 1 & 2: Cleans repeated headers and summary rows from CSV and normalizes."""
    await _seed_test_carrier_c(db_session)

    csv_content = (
        b"tracking_number,status,event_time\n"
        b"TRK-TYPEC-001,DISPATCHED,2026-10-20T10:00:00Z\n"
        b"tracking_number,status,event_time\n"  # Encabezado repetido (Defecto 5.3)
        b"TRK-TYPEC-002,IN_DEPOT,20/10/2026 11:30:00\n"  # Fecha DD/MM (Defecto 5.3)
        b"TOTAL REGISTROS,2,SUBTOTAL\n"  # Fila de totales (Defecto 5.3)
    )

    service = TypeCConnectorService()
    result = await service.process_file_content(
        db=db_session,
        filename="transexpress_batch_001.csv",
        content=csv_content,
        carrier_name="TransExpress Logistics",
    )

    assert result.status == "completed"
    assert result.total_rows_read == 4
    assert result.valid_rows_processed == 2
    assert result.header_rows_skipped == 1
    assert result.total_rows_skipped == 2  # 1 cabecera repetida + 1 fila de totales

    # Verificar que las guías se actualizaron en la BD (Subtarea 2)
    l1 = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-TYPEC-001")
        )
    ).scalar_one()
    assert l1.status == "PICKED_UP"

    l2 = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-TYPEC-002")
        )
    ).scalar_one()
    assert l2.status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_type_c_excel_reader_cleans_and_normalizes(db_session):
    """Subtask 1 & 2: Reads Excel (.xlsx), cleans summary rows and normalizes."""
    await _seed_test_carrier_c(db_session)

    # Crear libro de Excel en memoria
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["guia", "estado", "fecha"])
    ws.append(["TRK-TYPEC-001", "DISPATCHED", "2026-10-20T08:00:00Z"])
    ws.append(["guia", "estado", "fecha"])  # Cabecera repetida
    ws.append(["TRK-TYPEC-002", "IN_DEPOT", "2026-10-20T09:00:00Z"])
    ws.append(["TOTAL", "2", ""])  # Fila de total

    stream = io.BytesIO()
    wb.save(stream)
    excel_bytes = stream.getvalue()

    service = TypeCConnectorService()
    result = await service.process_file_content(
        db=db_session,
        filename="transexpress_daily.xlsx",
        content=excel_bytes,
        carrier_name="TransExpress Logistics",
    )

    assert result.status == "completed"
    assert result.valid_rows_processed == 2
    assert result.header_rows_skipped == 1
    assert result.total_rows_skipped == 2


@pytest.mark.asyncio
async def test_type_c_marks_processed_files_to_prevent_duplicates(db_session):
    """Subtask 3: Processed files are recorded and prevented from duplicate ingestion (CT-08)."""
    await _seed_test_carrier_c(db_session)

    csv_content = b"tracking_number,status\nTRK-TYPEC-001,DISPATCHED\n"

    service = TypeCConnectorService()

    # Primer procesamiento: Debe completarse con éxito
    result_1 = await service.process_file_content(
        db=db_session,
        filename="unique_batch_001.csv",
        content=csv_content,
        carrier_name="TransExpress Logistics",
    )
    assert result_1.status == "completed"
    assert result_1.already_processed is False

    # Verificar que quedó registrado en la tabla processed_files
    record = (
        await db_session.execute(
            select(ProcessedFile).where(ProcessedFile.filename == "unique_batch_001.csv")
        )
    ).scalar_one_or_none()
    assert record is not None
    assert record.valid_records == 1

    # Segundo procesamiento del mismo archivo: Debe ser omitido
    result_2 = await service.process_file_content(
        db=db_session,
        filename="unique_batch_001.csv",
        content=csv_content,
        carrier_name="TransExpress Logistics",
    )
    assert result_2.status == "skipped"
    assert result_2.already_processed is True
    assert result_2.valid_rows_processed == 0


@pytest.mark.asyncio
async def test_type_c_enforces_rn02_anomaly_on_delivered_status(db_session):
    """Subtask 2: Reusing normalization ensures RN-02 terminal state protection."""
    await _seed_test_carrier_c(db_session)

    # Intento de retroceder un paquete ya entregado
    csv_content = b"tracking_number,status\nTRK-TYPEC-DELIVERED,DISPATCHED\n"

    service = TypeCConnectorService()
    result = await service.process_file_content(
        db=db_session,
        filename="reversion_attempt.csv",
        content=csv_content,
        carrier_name="TransExpress Logistics",
    )

    assert result.status == "completed"
    assert result.anomalies_detected == 1

    # Verificar que el paquete sigue DELIVERED
    label = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-TYPEC-DELIVERED")
        )
    ).scalar_one()
    assert label.status == "DELIVERED"

    # Verificar que se registró la anomalía en tracking_anomalies
    anomaly = (
        await db_session.execute(
            select(TrackingAnomaly).where(TrackingAnomaly.tracking_number == "TRK-TYPEC-DELIVERED")
        )
    ).scalar_one_or_none()
    assert anomaly is not None
    assert anomaly.anomaly_type == "TERMINAL_STATE_REVERSION"


@pytest.mark.asyncio
async def test_type_c_upload_api_endpoint(client, db_session):
    """Test API endpoint POST /api/v1/sync/type-c/upload."""
    await _seed_test_carrier_c(db_session)

    csv_file = io.BytesIO(b"tracking_number,status\nTRK-TYPEC-001,DISPATCHED\n")

    response = await client.post(
        "/api/v1/sync/type-c/upload",
        files={"file": ("upload_test.csv", csv_file, "text/csv")},
        data={"carrier_name": "TransExpress Logistics"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["filename"] == "upload_test.csv"
    assert body["valid_rows_processed"] == 1
    assert body["already_processed"] is False


@pytest.mark.asyncio
async def test_type_c_unsupported_file_extension(db_session):
    service = TypeCConnectorService()
    res = await service.process_file_content(
        db=db_session,
        filename="unsupported.pdf",
        content=b"%PDF-1.4...",
        carrier_name="TransExpress Logistics",
    )
    assert res.status == "failed"
    assert "Unsupported file extension" in res.message


@pytest.mark.asyncio
async def test_type_c_missing_required_columns(db_session):
    service = TypeCConnectorService()
    res = await service.process_file_content(
        db=db_session,
        filename="missing_cols.csv",
        content=b"col_a,col_b\nval_a,val_b\n",
        carrier_name="TransExpress Logistics",
    )
    assert res.status == "failed"
    assert "Missing required columns" in res.message


@pytest.mark.asyncio
async def test_type_c_empty_csv(db_session):
    service = TypeCConnectorService()
    res = await service.process_file_content(
        db=db_session,
        filename="empty.csv",
        content=b"",
        carrier_name="TransExpress Logistics",
    )
    assert res.status == "completed"
    assert "File is empty" in res.message


def test_parse_mixed_datetime_formats():
    from datetime import UTC, datetime

    from app.services.type_c_connector import parse_mixed_datetime

    # Datetime object directly with UTC
    now = datetime(2026, 3, 29, 10, 0, 0, tzinfo=UTC)
    assert parse_mixed_datetime(now) == now

    # ISO format
    iso_dt = parse_mixed_datetime("2026-03-29T15:30:00")
    assert iso_dt is not None
    assert iso_dt.year == 2026

    # DD/MM/YYYY
    dmy_dt = parse_mixed_datetime("29/03/2026 15:30:00")
    assert dmy_dt is not None
    assert dmy_dt.day == 29

    # Empty / None
    assert parse_mixed_datetime(None) is None
    assert parse_mixed_datetime("") is None
    assert parse_mixed_datetime("   ") is None
    assert parse_mixed_datetime("unparseable-date") is None
