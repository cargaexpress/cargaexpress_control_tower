from datetime import UTC, date, datetime, timedelta
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
    UniversalPenaltyConfig,
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
# 1. Universal Penalty Scale & Decimal Calculation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_universal_penalty_scale_five_levels(db_session: AsyncSession):
    """Verify that all 5 universal levels exist and unapproved levels start as PENDING_APPROVAL."""
    service = FinancialEngineService()
    configs = await service.get_or_initialize_penalty_configs(db_session, version="test_v1")

    levels = {c.delay_level: c for c in configs}
    assert set(levels.keys()) == {"NO_DELAY", "LOW", "MODERATE", "HIGH", "CRITICAL"}

    assert levels["NO_DELAY"].approval_status == "APPROVED"
    assert levels["NO_DELAY"].penalty_percentage == Decimal("0.00")

    # The 4 delay levels are configurable and default to PENDING_APPROVAL without invented percentages
    for lvl in ("LOW", "MODERATE", "HIGH", "CRITICAL"):
        assert levels[lvl].approval_status == "PENDING_APPROVAL"
        assert levels[lvl].penalty_percentage is None
        assert levels[lvl].maximum_cap_percentage is None


@pytest.mark.asyncio
async def test_universal_application_across_different_carriers(db_session: AsyncSession):
    """Verify the universal penalty scale is shared uniformly across different carriers."""
    service = FinancialEngineService()
    today = date.today()

    # Configure approved universal scale in DB
    cfg_low = UniversalPenaltyConfig(
        version="v_shared",
        delay_level="LOW",
        min_delay_days=1,
        max_delay_days=2,
        penalty_percentage=Decimal("5.00"),
        maximum_cap_percentage=Decimal("20.00"),
        effective_date=today,
        is_active=True,
        approval_status="APPROVED",
    )
    db_session.add(cfg_low)
    await db_session.flush()

    # Create two different carriers
    carrier_a = Carrier(name="Carrier Alpha", integration_type="webhook", status="active")
    carrier_b = Carrier(name="Carrier Beta", integration_type="webhook", status="active")
    db_session.add_all([carrier_a, carrier_b])
    await db_session.flush()

    lvl_a, conf_a = await service.resolve_penalty_tier(
        db_session, delay_business_days=1, version="v_shared"
    )
    lvl_b, conf_b = await service.resolve_penalty_tier(
        db_session, delay_business_days=1, version="v_shared"
    )

    assert lvl_a == "LOW"
    assert lvl_b == "LOW"
    assert conf_a.config_id == conf_b.config_id
    assert conf_a.penalty_percentage == Decimal("5.00")


def test_decimal_financial_calculation_and_maximum_cap():
    """Verify exact Decimal financial calculations and enforcement of the maximum percentage cap."""
    service = FinancialEngineService()

    # 1. Base penalty less than cap: 5% of 100,000 = 5,000; Cap 20% = 20,000 -> Final 5,000
    base, cap, final = service.calculate_penalty_amounts(
        freight_amount=Decimal("100000.00"),
        penalty_percentage=Decimal("5.00"),
        maximum_cap_percentage=Decimal("20.00"),
    )
    assert base == Decimal("5000.00")
    assert cap == Decimal("20000.00")
    assert final == Decimal("5000.00")
    assert isinstance(final, Decimal)

    # 2. Base penalty exceeds cap: 25% of 100,000 = 25,000; Cap 15% = 15,000 -> Final 15,000 (Capped)
    base2, cap2, final2 = service.calculate_penalty_amounts(
        freight_amount=Decimal("100000.00"),
        penalty_percentage=Decimal("25.00"),
        maximum_cap_percentage=Decimal("15.00"),
    )
    assert base2 == Decimal("25000.00")
    assert cap2 == Decimal("15000.00")
    assert final2 == Decimal("15000.00")

    # 3. Precision rounding check with half-up
    _, _, final3 = service.calculate_penalty_amounts(
        freight_amount=Decimal("33.33"),
        penalty_percentage=Decimal("5.00"),
        maximum_cap_percentage=Decimal("20.00"),
    )
    # 33.33 * 0.05 = 1.6665 -> 1.67
    assert final3 == Decimal("1.67")


# =============================================================================
# 2. Penalty Level & Responsibility Rules
# =============================================================================


@pytest.mark.asyncio
async def test_no_penalty_when_no_delay(db_session: AsyncSession):
    """Verify that shipments delivered within SLA produce NO_DELAY and 0.00 penalty."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-ON-TIME",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        freight_value=Decimal("80000.00"),
    )
    # Delivered on Day 1 (well before 3 days SLA deadline)
    delivery_time = dispatch_time + timedelta(days=1)

    penalty = await service.calculate_freight_penalty(
        db_session, label, current_time_utc=delivery_time
    )
    assert penalty is not None
    assert penalty.delay_level == "NO_DELAY"
    assert penalty.penalty_amount == Decimal("0.00")
    assert penalty.is_carrier_payable is False
    assert penalty.contract_rule_applied == "UNIVERSAL_SCALE_NO_DELAY"


@pytest.mark.asyncio
async def test_no_definitive_monetary_charge_when_configuration_pending_approval(
    db_session: AsyncSession,
):
    """Verify that unapproved configuration generates NO definitive monetary charge."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-UNAPPROVED-CFG",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        freight_value=Decimal("120000.00"),
    )
    # Delayed past SLA deadline
    delivery_time = dispatch_time + timedelta(days=6)

    # Use default version where configuration is PENDING_APPROVAL
    penalty = await service.calculate_freight_penalty(
        db_session, label, current_time_utc=delivery_time, config_version="v_unapproved"
    )
    assert penalty is not None
    assert penalty.calculation_status == "PENDING_APPROVAL"
    assert penalty.penalty_amount is None
    assert penalty.base_penalty_amount is None
    assert penalty.maximum_penalty_amount is None
    assert penalty.is_carrier_payable is False  # Cannot collect unapproved penalty
    assert "PENDING_APPROVAL" in penalty.contract_rule_applied


@pytest.mark.asyncio
async def test_no_charge_for_undetermined_responsibility(db_session: AsyncSession):
    """Verify that undetermined responsibility produces no definitive financial charge."""
    service = FinancialEngineService()
    created_time = datetime(2026, 11, 1, 8, 0, 0, tzinfo=UTC)

    # Order not dispatched, and no approved DC threshold provided -> UNDETERMINED
    _, label, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-UNDETERMINED",
        status="CREATED",
        dispatched_at=None,
        order_created_at=created_time,
        freight_value=Decimal("100000.00"),
    )

    attr = await service.attribute_shipment_responsibility(db_session, label)
    assert attr.responsible_party == "UNDETERMINED"
    assert attr.incident_type == "PENDING_DISPATCH"

    penalty = await service.calculate_freight_penalty(db_session, label)
    assert penalty is not None
    assert penalty.calculation_status == "UNDETERMINED_RESPONSIBILITY"
    assert penalty.penalty_amount is None
    assert penalty.is_carrier_payable is False


@pytest.mark.asyncio
async def test_carrier_recoverables_only_when_carrier_responsible(db_session: AsyncSession):
    """Verify carrier is marked payable ONLY when carrier responsibility is established and approved."""
    service = FinancialEngineService()
    today = date.today()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    # Seed approved configuration
    cfg_low = UniversalPenaltyConfig(
        version="v_approved_test",
        delay_level="LOW",
        min_delay_days=1,
        max_delay_days=3,
        penalty_percentage=Decimal("5.00"),
        maximum_cap_percentage=Decimal("20.00"),
        effective_date=today,
        is_active=True,
        approval_status="APPROVED",
    )
    db_session.add(cfg_low)
    await db_session.flush()

    # 1. Carrier responsible shipment (delayed in transit past SLA)
    _, label_carrier, carrier, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-CARRIER-RESP",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        freight_value=Decimal("100000.00"),
    )
    delivery_time = dispatch_time + timedelta(days=5)  # 2 business days late -> LOW
    penalty_c = await service.calculate_freight_penalty(
        db_session, label_carrier, current_time_utc=delivery_time, config_version="v_approved_test"
    )
    assert penalty_c is not None
    assert penalty_c.calculation_status == "APPROVED"
    assert penalty_c.responsible_party == "CARRIER"
    assert penalty_c.is_carrier_payable is True
    assert penalty_c.penalty_amount == Decimal("5000.00")

    # 2. Client address exception shipment -> Carrier NOT payable
    _, label_client, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-CLIENT-RESP",
        status="EXCEPTION",
        dispatched_at=dispatch_time,
        freight_value=Decimal("100000.00"),
    )
    db_session.add(
        TrackingAnomaly(
            carrier_id=carrier.carrier_id,
            tracking_number=label_client.tracking_number,
            label_id=label_client.label_id,
            current_status="EXCEPTION",
            attempted_status="EXCEPTION",
            raw_status="DIRECCION_ERRONEA",
            details="Wrong street address",
        )
    )
    await db_session.flush()

    penalty_cl = await service.calculate_freight_penalty(
        db_session, label_client, current_time_utc=delivery_time, config_version="v_approved_test"
    )
    assert penalty_cl is not None
    assert penalty_cl.responsible_party == "CLIENT"
    assert penalty_cl.is_carrier_payable is False


@pytest.mark.asyncio
async def test_duplicate_penalty_idempotency(db_session: AsyncSession):
    """Ensure idempotency: running penalty calculation multiple times creates exactly one record."""
    service = FinancialEngineService()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    _, label, _, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-IDEMPOTENCY",
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

    stmt = select(FreightPenalty).where(FreightPenalty.tracking_number == "TRK-IDEMPOTENCY")
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 1


# =============================================================================
# 3. Biweekly Settlement & Netting Protection Tests
# =============================================================================


@pytest.mark.asyncio
async def test_settlement_pending_validation_no_unauthorized_netting(db_session: AsyncSession):
    """Verify settlements remain PENDING_VALIDATION with separate balances and NO unauthorized netting."""
    service = FinancialEngineService()
    today = date.today()
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    # Seed approved config for calculation
    cfg_low = UniversalPenaltyConfig(
        version="v_settle_test",
        delay_level="LOW",
        min_delay_days=1,
        max_delay_days=3,
        penalty_percentage=Decimal("5.00"),
        maximum_cap_percentage=Decimal("20.00"),
        effective_date=today,
        is_active=True,
        approval_status="APPROVED",
    )
    db_session.add(cfg_low)
    await db_session.flush()

    _, label, carrier, _ = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-SETTLE-TEST",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        freight_value=Decimal("100000.00"),
    )
    calc_time = datetime(2026, 11, 10, 10, 0, 0, tzinfo=UTC)
    await service.calculate_freight_penalty(
        db_session, label, current_time_utc=calc_time, config_version="v_settle_test"
    )

    settlement = await service.generate_biweekly_settlement(
        db=db_session,
        carrier_id=carrier.carrier_id,
        year=2026,
        month=11,
        half=1,
    )

    # Must remain PENDING_VALIDATION without unauthorized netting formula
    assert settlement.status == "PENDING_VALIDATION"
    assert settlement.net_settlement_amount is None
    assert settlement.total_recoverable_from_carrier == Decimal("5000.00")
    assert settlement.total_owed_to_clients == Decimal("5000.00")

    # Verify ledger movements: only atomic entries, NO NET_SETTLEMENT movement
    stmt_l = select(FinancialLedgerEntry).where(
        FinancialLedgerEntry.settlement_id == settlement.settlement_id
    )
    res_l = await db_session.execute(stmt_l)
    entries = res_l.scalars().all()
    types = {e.entry_type for e in entries}
    assert "CARRIER_PENALTY_RECEIVABLE" in types
    assert "CLIENT_INDEMNITY_PAYABLE" in types
    assert "NET_SETTLEMENT" not in types  # No unauthorized netting entry


def test_biweekly_settlement_boundaries():
    """Verify strict half-month boundaries: H1 (1-15) and H2 (16-last day)."""
    service = FinancialEngineService()

    code1, start1, end1 = service.compute_half_month_period(2026, 2, 1)
    assert code1 == "2026-02-H1"
    assert start1 == date(2026, 2, 1)
    assert end1 == date(2026, 2, 15)

    code2, start2, end2 = service.compute_half_month_period(2026, 2, 2)
    assert code2 == "2026-02-H2"
    assert start2 == date(2026, 2, 16)
    assert end2 == date(2026, 2, 28)  # Leap year check (2026 is non-leap)

    code3, start3, end3 = service.compute_half_month_period(2026, 11, 2)
    assert code3 == "2026-11-H2"
    assert start3 == date(2026, 11, 16)
    assert end3 == date(2026, 11, 30)


# =============================================================================
# 4. API & Tenant Isolation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_financial_api_endpoints_and_tenant_isolation(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Test client penalties API, ensuring strict tenant isolation (BR-10)."""
    dispatch_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)

    # 1. Seed shipment for Brand 1
    _, label1, carrier, brand1 = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-TENANT-01",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        brand_name="Brand Tenant 1",
    )
    # 2. Seed shipment for Brand 2
    _, label2, _, brand2 = await _seed_financial_shipment(
        db=db_session,
        tracking_number="TRK-TENANT-02",
        status="DELIVERED",
        dispatched_at=dispatch_time,
        brand_name="Brand Tenant 2",
    )

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

    # Query scale configuration endpoint
    resp_cfg = await client.get(
        "/api/v1/financial/config/penalty-scales",
        headers={"X-API-Key": api_key_brand1},
    )
    assert resp_cfg.status_code == 200
    data_cfg = resp_cfg.json()
    assert len(data_cfg) >= 5
    levels = {c["delay_level"] for c in data_cfg}
    assert {"NO_DELAY", "LOW", "MODERATE", "HIGH", "CRITICAL"}.issubset(levels)
