"""Unit tests for NormalizationService and business rules (RN-01, RN-02, RN-07)."""

from decimal import Decimal

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
from app.services.exceptions import EntityNotFoundError
from app.services.normalization_service import (
    find_carrier_by_slug_or_id,
    normalize_and_apply_event,
)
from app.services.state_mapping_cache import state_mapping_cache


async def _seed_test_data(db_session):
    brand = Brand(brand_id=1, name="Test Brand", tier="enterprise", is_active=True)
    dc = DistributionCenter(
        dc_id=1, code="BOG01", name="Bogota Hub", city="Bogota", country_code="CO"
    )
    ship_type = ShipmentType(shipment_type_code="EXP", description="Express Delivery")
    carrier = Carrier(
        carrier_id=1, name="SimCarrier Test", integration_type="webhook", status="active"
    )

    db_session.add_all([brand, dc, ship_type, carrier])
    await db_session.commit()

    mappings = [
        StateMapping(id=1001, carrier_id=1, raw_status="TRANSIT_OK", canonical_status="IN_TRANSIT"),
        StateMapping(
            id=1002, carrier_id=1, raw_status="OUT_NOW", canonical_status="OUT_FOR_DELIVERY"
        ),
        StateMapping(id=1003, carrier_id=1, raw_status="DELIV_DONE", canonical_status="DELIVERED"),
    ]
    db_session.add_all(mappings)
    await db_session.commit()
    state_mapping_cache.invalidate()

    order = Order(
        order_id=1,
        brand_id=1,
        dc_id=1,
        shipment_type_code="EXP",
        brand_order_ref="ORD-TEST-001",
        destination_country="CO",
        destination_region="Cundinamarca",
        freight_value=Decimal("25000.00"),
        status="CREATED",
        order_lines=[
            OrderLine(
                order_line_id=1,
                line_number=1,
                sku="SKU-1",
                description="Widget",
                quantity_ordered=2,
            )
        ],
        recipient=OrderRecipient(
            full_name="Juan Perez",
            email="juan@example.com",
            phone="+573001234567",
            address_line="Calle 100 #15-20",
            city="Bogota",
        ),
    )
    db_session.add(order)
    await db_session.commit()

    label1 = ShippingLabel(
        label_id=1,
        order_id=1,
        carrier_id=1,
        tracking_number="TRACK-NORM-001",
        status="CREATED",
    )
    label2 = ShippingLabel(
        label_id=2,
        order_id=1,
        carrier_id=1,
        tracking_number="TRACK-NORM-002",
        status="CREATED",
    )
    db_session.add_all([label1, label2])
    await db_session.commit()
    return carrier, order, label1, label2


@pytest.mark.asyncio
async def test_find_carrier_by_slug_or_id(db_session):
    carrier, _, _, _ = await _seed_test_data(db_session)

    # By int id
    by_int = await find_carrier_by_slug_or_id(db_session, 1)
    assert by_int is not None
    assert by_int.carrier_id == 1

    # By digit string
    by_str = await find_carrier_by_slug_or_id(db_session, "1")
    assert by_str is not None
    assert by_str.carrier_id == 1

    # By exact name case-insensitive
    by_name = await find_carrier_by_slug_or_id(db_session, "simcarrier test")
    assert by_name is not None

    # By substring
    by_sub = await find_carrier_by_slug_or_id(db_session, "test")
    assert by_sub is not None

    # Non-existent
    assert await find_carrier_by_slug_or_id(db_session, "nonexistent-carrier-xyz") is None


@pytest.mark.asyncio
async def test_normalize_raises_for_unknown_carrier(db_session):
    with pytest.raises(EntityNotFoundError):
        await normalize_and_apply_event(
            db=db_session,
            carrier_identifier="unknown-carrier",
            tracking_number="TRK-999",
            raw_status="ANY",
        )


@pytest.mark.asyncio
async def test_normalize_unmapped_status_falls_back_to_exception(db_session):
    await _seed_test_data(db_session)

    result = await normalize_and_apply_event(
        db=db_session,
        carrier_identifier=1,
        tracking_number="TRACK-NORM-001",
        raw_status="UNKNOWN_STATUS_CODE",
    )
    assert result.success is True
    assert result.canonical_status == "EXCEPTION"


@pytest.mark.asyncio
async def test_normalize_propagates_in_transit_and_out_for_delivery_to_order(db_session):
    _, order, label1, _ = await _seed_test_data(db_session)

    # In transit propagates
    res1 = await normalize_and_apply_event(
        db=db_session,
        carrier_identifier=1,
        tracking_number=label1.tracking_number,
        raw_status="TRANSIT_OK",
    )
    assert res1.canonical_status == "IN_TRANSIT"
    await db_session.refresh(order)
    assert order.status == "IN_TRANSIT"

    # Out for delivery propagates
    res2 = await normalize_and_apply_event(
        db=db_session,
        carrier_identifier=1,
        tracking_number=label1.tracking_number,
        raw_status="OUT_NOW",
    )
    assert res2.canonical_status == "OUT_FOR_DELIVERY"
    await db_session.refresh(order)
    assert order.status == "OUT_FOR_DELIVERY"


@pytest.mark.asyncio
async def test_normalize_delivered_order_propagation_when_split(db_session):
    """RN-07: Order only transitions to DELIVERED when all labels are delivered."""
    _, order, label1, label2 = await _seed_test_data(db_session)

    # Deliver label 1: label 2 is still CREATED -> order should NOT be DELIVERED
    await normalize_and_apply_event(
        db=db_session,
        carrier_identifier=1,
        tracking_number=label1.tracking_number,
        raw_status="DELIV_DONE",
    )
    await db_session.refresh(order)
    assert order.status != "DELIVERED"

    # Deliver label 2: now all labels delivered -> order must be DELIVERED
    await normalize_and_apply_event(
        db=db_session,
        carrier_identifier=1,
        tracking_number=label2.tracking_number,
        raw_status="DELIV_DONE",
    )
    await db_session.refresh(order)
    assert order.status == "DELIVERED"

    # Idempotent delivery event does not raise anomaly
    idemp_res = await normalize_and_apply_event(
        db=db_session,
        carrier_identifier=1,
        tracking_number=label2.tracking_number,
        raw_status="DELIV_DONE",
    )
    assert idemp_res.success is True
    assert idemp_res.is_anomaly is False
    assert idemp_res.message == "Status already at target terminal state."
