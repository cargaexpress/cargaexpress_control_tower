from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.dispatch import Dispatch
from app.models.distribution_center import DistributionCenter
from app.models.financial import (
    FinancialLedgerEntry,
    FreightPenalty,
)
from app.models.order import Order
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.tracking_anomaly import TrackingAnomaly
from app.services.financial_engine import FinancialEngineService


async def _seed_financial_shipment(
    db: AsyncSession,
    tracking_number: str,
    status: str,
    dispatched_at: datetime | None,
    freight_value: Decimal = Decimal("100000.00"),
    order_created_at: datetime | None = None,
    destination_region: str | None = None,
    brand_name: str = "TestBrand Fin",
    carrier: Carrier | None = None,
) -> tuple[Order, ShippingLabel, Carrier, Brand]:
    brand = Brand(name=brand_name, tier="TIER_1", is_active=True)
    dc = DistributionCenter(
        code=f"DC-{tracking_number[:6]}", name="DC Test", city="Bogota", country_code="CO"
    )
    if carrier is None:
        carrier = Carrier(name="SimCarrier Alpha", integration_type="webhook", status="active")
        db.add(carrier)

    # Reuse existing shipment type if already seeded
    stmt_st = select(ShipmentType).where(ShipmentType.shipment_type_code == "STANDARD")
    res_st = await db.execute(stmt_st)
    st = res_st.scalar_one_or_none()
    if not st:
        st = ShipmentType(shipment_type_code="STANDARD", description="Standard shipping")
        db.add(st)

    db.add_all([brand, dc])
    await db.flush()

    order = Order(
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code="STANDARD",
        brand_order_ref=f"REF-{tracking_number}",
        destination_country="CO",
        destination_region=destination_region,
        freight_value=freight_value,
        status=status,
    )
    if order_created_at:
        order.created_at = order_created_at
    db.add(order)
    await db.flush()

    dispatch_id = None
    if dispatched_at:
        dispatch = Dispatch(
            dc_id=dc.dc_id,
            carrier_id=carrier.carrier_id,
            dispatched_at=dispatched_at,
        )
        db.add(dispatch)
        await db.flush()
        dispatch_id = dispatch.dispatch_id

    label = ShippingLabel(
        order_id=order.order_id,
        carrier_id=carrier.carrier_id,
        tracking_number=tracking_number,
        dispatch_id=dispatch_id,
        status=status,
    )
    db.add(label)
    await db.flush()
    return order, label, carrier, brand


# =============================================================================
# 1. Responsibility Attribution Tests (BR-05)
# =============================================================================


@pytest.mark.asyncio
async def test_attribution_distribution_center_when_delayed_before_dispatch(
    db_session: AsyncSession,
):
    """SCN-04: Dispatch took > 48 hours -> Distribution Center responsible."""
    service = FinancialEngineService()
    created_time = datetime(2026, 11, 1, 8, 0, 0, tzinfo=UTC)
    now = created_time + timedelta(hours=54)

    order, label, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-DC-DELAY",
        status="CREATED",
        dispatched_at=None,
        order_created_at=created_time,
    )

    attr = await service.attribute_shipment_responsibility(db_session, label, current_time_utc=now)
    assert attr.responsible_party == "DISTRIBUTION_CENTER"
    assert attr.incident_type == "DISPATCH_DELAY"
    assert "distribution center" in attr.reason.lower()


@pytest.mark.asyncio
async def test_attribution_carrier_when_delayed_in_transit(db_session: AsyncSession):
    """SCN-03: Carrier delivered past SLA deadline -> Carrier responsible."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    order, label, carrier, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-CARRIER-DELAY",
        status="DELIVERED",
        dispatched_at=dispatch_time,
    )

    # 6 days later (past 3 days SLA deadline)
    delivery_time = dispatch_time + timedelta(days=6)
    attr = await service.attribute_shipment_responsibility(
        db_session, label, current_time_utc=delivery_time
    )
    assert attr.responsible_party == "CARRIER"
    assert attr.incident_type == "SLA_BREACH"
    assert "exceeded sla delivery deadline" in attr.reason.lower()


@pytest.mark.asyncio
async def test_attribution_client_when_incorrect_address_exception(db_session: AsyncSession):
    """SCN-05: Delivery issue caused by incorrect address -> Client responsible."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    order, label, carrier, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-CLIENT-ADDR",
        status="EXCEPTION",
        dispatched_at=dispatch_time,
    )

    # Add anomaly marking incorrect address
    anomaly = TrackingAnomaly(
        carrier_id=carrier.carrier_id,
        tracking_number=label.tracking_number,
        label_id=label.label_id,
        current_status="EXCEPTION",
        attempted_status="EXCEPTION",
        raw_status="DIRECCION_ERRONEA",
        anomaly_type="ADDRESS_EXCEPTION",
        details="Delivery failed: incorrect recipient address supplied",
    )
    db_session.add(anomaly)
    await db_session.flush()

    attr = await service.attribute_shipment_responsibility(db_session, label)
    assert attr.responsible_party == "CLIENT"
    assert attr.incident_type == "ADDRESS_EXCEPTION"
    assert "incorrect address" in attr.reason.lower()


# =============================================================================
# 2. Penalty Calculation Tests (BR-06)
# =============================================================================


@pytest.mark.asyncio
async def test_penalty_transferred_to_carrier_only_when_carrier_responsible(
    db_session: AsyncSession,
):
    """BR-06: 1-2 days late -> 5%, transferred to carrier ONLY if carrier is responsible."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    # 1. Carrier responsible shipment
    order_c, label_c, carrier, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-PENALTY-CARRIER",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        freight_value=Decimal("100000.00"),
    )
    delivery_time = dispatch_time + timedelta(days=5)  # 2 days past SLA deadline
    penalty_c = await service.calculate_freight_penalty(
        db_session, label_c, current_time_utc=delivery_time
    )

    assert penalty_c is not None
    assert penalty_c.is_carrier_payable is True
    assert penalty_c.responsible_party == "CARRIER"
    assert penalty_c.penalty_percentage == Decimal("5.00")
    assert penalty_c.penalty_amount == Decimal("5000.00")  # 5% of 100,000

    # 2. Client address exception shipment -> Carrier is NOT charged
    order_cl, label_cl, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-NO-PENALTY-CLIENT",
        status="EXCEPTION",
        dispatched_at=dispatch_time,
        freight_value=Decimal("100000.00"),
    )
    db_session.add(
        TrackingAnomaly(
            carrier_id=carrier.carrier_id,
            tracking_number=label_cl.tracking_number,
            label_id=label_cl.label_id,
            current_status="EXCEPTION",
            attempted_status="EXCEPTION",
            raw_status="DIRECCION_ERRONEA",
            details="Wrong address",
        )
    )
    await db_session.flush()

    penalty_cl = await service.calculate_freight_penalty(
        db_session, label_cl, current_time_utc=delivery_time
    )
    assert penalty_cl is not None
    assert penalty_cl.is_carrier_payable is False
    assert penalty_cl.responsible_party == "CLIENT"


@pytest.mark.asyncio
async def test_duplicate_penalty_prevention(db_session: AsyncSession):
    """Ensure idempotency: running penalty calculation multiple times creates exactly one penalty record."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-DUP-PENALTY",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        freight_value=Decimal("50000.00"),
    )
    delivery_time = dispatch_time + timedelta(days=5)

    p1 = await service.calculate_freight_penalty(db_session, label, current_time_utc=delivery_time)
    p2 = await service.calculate_freight_penalty(db_session, label, current_time_utc=delivery_time)

    assert p1 is not None
    assert p2 is not None
    assert p1.penalty_id == p2.penalty_id

    # Count records in table
    stmt = select(FreightPenalty).where(FreightPenalty.tracking_number == "TRK-DUP-PENALTY")
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 1


# =============================================================================
# 3. Biweekly Settlement and Netting Tests (FR-05, BR-08)
# =============================================================================


@pytest.mark.asyncio
async def test_biweekly_settlement_and_netting_calculation(db_session: AsyncSession):
    """FR-05, BR-08: Generate H1 settlement, group by carrier, calculate net amount and ledger entries."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    # Seed carrier delayed shipment ($100,000 freight -> $5,000 penalty)
    _, label_carrier, carrier, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-SETTLE-01",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        freight_value=Decimal("100000.00"),
    )
    # Seed DC delayed shipment ($200,000 freight -> $10,000 penalty owed to client, NOT carrier payable)
    _, label_dc, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-SETTLE-02",
        status="CREATED",
        dispatched_at=None,
        freight_value=Decimal("200000.00"),
        order_created_at=datetime(2026, 11, 1, 8, 0, 0, tzinfo=UTC),
        carrier=carrier,
    )

    # Calculate penalties in early November (H1 period: Nov 1-15)
    calc_time = datetime(2026, 11, 7, 10, 0, 0, tzinfo=UTC)
    p_carrier = await service.calculate_freight_penalty(
        db_session, label_carrier, current_time_utc=calc_time
    )
    p_dc = await service.calculate_freight_penalty(db_session, label_dc, current_time_utc=calc_time)

    assert p_carrier is not None
    assert p_dc is not None

    # Generate H1 settlement for carrier
    settlement = await service.generate_biweekly_settlement(
        db=db_session,
        carrier_id=carrier.carrier_id,
        year=2026,
        month=11,
        half=1,
    )

    assert settlement.period_code == "2026-11-H1"
    assert settlement.carrier_id == carrier.carrier_id
    assert settlement.status == "CLOSED"
    assert settlement.total_penalties_count == 2
    assert settlement.total_owed_to_clients == p_carrier.penalty_amount + p_dc.penalty_amount
    assert settlement.total_recoverable_from_carrier == p_carrier.penalty_amount
    # Net amount: owed to clients minus recoverable from carrier
    assert (
        settlement.net_settlement_amount
        == settlement.total_owed_to_clients - settlement.total_recoverable_from_carrier
    )

    # Verify audit ledger movements created
    stmt_ledger = select(FinancialLedgerEntry).where(
        FinancialLedgerEntry.settlement_id == settlement.settlement_id
    )
    res_l = await db_session.execute(stmt_ledger)
    entries = res_l.scalars().all()
    assert len(entries) >= 3
    types = {e.entry_type for e in entries}
    assert "CLIENT_INDEMNITY_PAYABLE" in types
    assert "CARRIER_PENALTY_RECEIVABLE" in types
    assert "NET_SETTLEMENT" in types


# =============================================================================
# 4. API Endpoints & Tenant Isolation Tests (FR-06, BR-10)
# =============================================================================


@pytest.mark.asyncio
async def test_financial_api_endpoints_and_tenant_isolation(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Test client penalties API, ensuring recipient/tenant isolation (BR-10)."""
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    # 1. Seed shipment for Brand 1
    order1, label1, carrier, brand1 = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-TENANT-01",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        brand_name="Brand Tenant 1",
    )
    # 2. Seed shipment for Brand 2
    order2, label2, _, brand2 = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-TENANT-02",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        brand_name="Brand Tenant 2",
    )

    # Calculate penalties
    service = FinancialEngineService()
    delivery_time = dispatch_time + timedelta(days=6)
    await service.calculate_freight_penalty(db_session, label1, current_time_utc=delivery_time)
    await service.calculate_freight_penalty(db_session, label2, current_time_utc=delivery_time)
    await db_session.commit()

    # Authenticate client as Brand 1
    api_key_brand1 = "brand1_api_key_32_characters_long"
    monkeypatch.setattr(settings, "brand_api_keys", {api_key_brand1: brand1.brand_id})

    # Query GET /api/v1/financial/penalties with Brand 1 key
    resp1 = await client.get("/api/v1/financial/penalties", headers={"X-API-Key": api_key_brand1})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1) == 1
    assert data1[0]["tracking_number"] == "TRK-TENANT-01"
    assert data1[0]["brand_id"] == brand1.brand_id

    # Brand 1 attempts to query attribution for Brand 2's tracking -> Must be 403 Forbidden (BR-10)
    resp_forbidden = await client.get(
        f"/api/v1/financial/attributions/tracking/{label2.tracking_number}",
        headers={"X-API-Key": api_key_brand1},
    )
    assert resp_forbidden.status_code == 403
    assert "belongs to another client" in resp_forbidden.json()["detail"].lower()

    # Carrier penalties query (FR-07)
    resp_carrier = await client.get(
        f"/api/v1/financial/carrier/{carrier.carrier_id}/penalties",
        headers={"X-API-Key": api_key_brand1},
    )
    assert resp_carrier.status_code == 200
    data_carrier = resp_carrier.json()
    assert len(data_carrier) >= 1
    assert all(p["carrier_id"] == carrier.carrier_id for p in data_carrier)
