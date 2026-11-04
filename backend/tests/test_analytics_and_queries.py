from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.analytics import (
    DimBrand,
    DimCarrier,
    DimDate,
    DimDistributionCenter,
    DimGeography,
    DimShipmentStatus,
    EtlRejectedRecord,
    FactFinancialPenalty,
    FactShipmentSla,
)
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.dispatch import Dispatch
from app.models.distribution_center import DistributionCenter
from app.models.financial import (
    UniversalPenaltyConfig,
)
from app.models.order import Order
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.services.analytical_etl import AnalyticalEtlService
from app.services.financial_engine import FinancialEngineService
from app.services.sla_engine import SlaEngineService


async def _seed_test_data(
    db: AsyncSession,
) -> tuple[Brand, Brand, Carrier, Carrier, ShippingLabel, ShippingLabel]:
    # 1. Brands
    brand1 = Brand(name="Acme Fashion", tier="TIER_1", is_active=True)
    brand2 = Brand(name="Beta Electronics", tier="TIER_2", is_active=True)

    # 2. Distribution Center
    dc = DistributionCenter(
        code="DC-BOG-01", name="Bogota Central", city="Bogota", country_code="CO"
    )

    # 3. Carriers
    carrier1 = Carrier(name="RapidExpress A", integration_type="webhook", status="active")
    carrier2 = Carrier(name="GlobalCargo B", integration_type="rest_api", status="active")

    # 4. Shipment Type
    st = ShipmentType(shipment_type_code="STANDARD", description="Standard Delivery")

    db.add_all([brand1, brand2, dc, carrier1, carrier2, st])
    await db.flush()

    # 5. Orders & Dispatches
    created_time = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)
    dispatch_time = datetime(2026, 11, 2, 10, 0, 0, tzinfo=UTC)

    order1 = Order(
        brand_id=brand1.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code="STANDARD",
        brand_order_ref="ORD-BRAND1-001",
        destination_country="CO",
        destination_region="ANDINA",
        freight_value=Decimal("150000.00"),
        status="DELIVERED",
    )
    order1.created_at = created_time

    order2 = Order(
        brand_id=brand2.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code="STANDARD",
        brand_order_ref="ORD-BRAND2-002",
        destination_country="CO",
        destination_region="CARIBE",
        freight_value=Decimal("200000.00"),
        status="DELIVERED",
    )
    order2.created_at = created_time

    db.add_all([order1, order2])
    await db.flush()

    dispatch1 = Dispatch(
        dc_id=dc.dc_id, carrier_id=carrier1.carrier_id, dispatched_at=dispatch_time
    )
    dispatch2 = Dispatch(
        dc_id=dc.dc_id, carrier_id=carrier2.carrier_id, dispatched_at=dispatch_time
    )
    db.add_all([dispatch1, dispatch2])
    await db.flush()

    # 6. Shipping Labels
    label1 = ShippingLabel(
        order_id=order1.order_id,
        carrier_id=carrier1.carrier_id,
        tracking_number="TRK-BRAND1-001",
        dispatch_id=dispatch1.dispatch_id,
        status="DELIVERED",
    )
    label2 = ShippingLabel(
        order_id=order2.order_id,
        carrier_id=carrier2.carrier_id,
        tracking_number="TRK-BRAND2-002",
        dispatch_id=dispatch2.dispatch_id,
        status="DELIVERED",
    )
    db.add_all([label1, label2])
    await db.flush()

    # 7. SLA Trackings
    sla_engine = SlaEngineService()
    # Evaluate SLA for label 1 (Compliant on time)
    delivery_time_1 = dispatch_time + timedelta(days=2)
    label1.status = "DELIVERED"
    await sla_engine.evaluate_shipment_sla(db, label1, current_time_utc=delivery_time_1)

    # Evaluate SLA for label 2 (Breached late by 6 days)
    delivery_time_2 = dispatch_time + timedelta(days=8)
    label2.status = "DELIVERED"
    await sla_engine.evaluate_shipment_sla(db, label2, current_time_utc=delivery_time_2)

    # 8. Seed approved universal penalty config
    cfg_low = UniversalPenaltyConfig(
        version="v1.0",
        delay_level="LOW",
        min_delay_days=1,
        max_delay_days=5,
        penalty_percentage=Decimal("10.00"),
        maximum_cap_percentage=Decimal("20.00"),
        effective_date=date.today(),
        is_active=True,
        approval_status="APPROVED",
    )
    db.add(cfg_low)
    await db.flush()

    # Calculate penalty for delayed label 2
    fin_engine = FinancialEngineService(sla_engine=sla_engine)
    await fin_engine.calculate_freight_penalty(
        db, label2, current_time_utc=delivery_time_2, config_version="v1.0"
    )

    await db.flush()
    return brand1, brand2, carrier1, carrier2, label1, label2


# =============================================================================
# Work Package 1: SLA and Penalty Query APIs for Brands and Carriers
# =============================================================================


@pytest.mark.asyncio
async def test_brand_sla_metrics_and_tenant_isolation(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Test Brand SLA metrics endpoint: validates shipment volume, compliance rate, and strict tenant isolation."""
    brand1, brand2, _, _, _, _ = await _seed_test_data(db_session)
    await db_session.commit()

    api_key_b1 = "key_brand_1_test_secret_32_chars_ok"
    api_key_b2 = "key_brand_2_test_secret_32_chars_ok"
    monkeypatch.setattr(
        settings,
        "brand_api_keys",
        {api_key_b1: brand1.brand_id, api_key_b2: brand2.brand_id},
    )

    # 1. Query metrics for Brand 1 (1 shipment, 100% compliant, 0 penalties)
    resp1 = await client.get("/api/v1/sla/brand/metrics", headers={"X-API-Key": api_key_b1})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["brand_id"] == brand1.brand_id
    assert data1["total_shipments"] == 1
    assert data1["compliant_shipments"] == 1
    assert data1["breached_shipments"] == 0
    assert float(data1["compliance_rate_pct"]) == 100.0
    assert float(data1["total_penalties_amount"]) == 0.0

    # 2. Query metrics for Brand 2 (1 shipment, 0% compliant, 1 breached, $20,000 penalty)
    resp2 = await client.get("/api/v1/sla/brand/metrics", headers={"X-API-Key": api_key_b2})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["brand_id"] == brand2.brand_id
    assert data2["total_shipments"] == 1
    assert data2["compliant_shipments"] == 0
    assert data2["breached_shipments"] == 1
    assert float(data2["compliance_rate_pct"]) == 0.0
    assert float(data2["total_penalties_amount"]) == 20000.0  # 10% of 200,000


@pytest.mark.asyncio
async def test_brand_shipments_paginated_and_history(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Test Brand detailed paginated shipments and daily history endpoints."""
    brand1, _, _, _, label1, _ = await _seed_test_data(db_session)
    await db_session.commit()

    api_key_b1 = "key_brand_1_test_secret_32_chars_ok"
    monkeypatch.setattr(settings, "brand_api_keys", {api_key_b1: brand1.brand_id})

    # Paginated shipments query
    resp_shipments = await client.get(
        "/api/v1/sla/brand/shipments?limit=10&offset=0",
        headers={"X-API-Key": api_key_b1},
    )
    assert resp_shipments.status_code == 200
    data_s = resp_shipments.json()
    assert data_s["total"] == 1
    assert len(data_s["items"]) == 1
    item = data_s["items"][0]
    assert item["tracking_number"] == label1.tracking_number
    assert item["brand_id"] == brand1.brand_id
    assert item["status"] == "DELIVERED"

    # Daily history query
    resp_hist = await client.get("/api/v1/sla/brand/history", headers={"X-API-Key": api_key_b1})
    assert resp_hist.status_code == 200
    data_h = resp_hist.json()
    assert len(data_h["periods"]) >= 1
    assert data_h["periods"][0]["total_shipments"] == 1


@pytest.mark.asyncio
async def test_carrier_sla_metrics_and_tenant_isolation(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Test Carrier SLA metrics and shipments query with strict carrier isolation."""
    _, _, carrier1, carrier2, _, label2 = await _seed_test_data(db_session)
    await db_session.commit()

    api_key_c1 = "key_carrier_1_secret_token_32_chars"
    api_key_c2 = "key_carrier_2_secret_token_32_chars"
    monkeypatch.setattr(
        settings,
        "carrier_api_keys",
        {api_key_c1: carrier1.carrier_id, api_key_c2: carrier2.carrier_id},
    )

    # 1. Carrier 1 (Carrier of label 1: compliant)
    resp_c1 = await client.get("/api/v1/sla/carrier/metrics", headers={"X-API-Key": api_key_c1})
    assert resp_c1.status_code == 200
    data_c1 = resp_c1.json()
    assert data_c1["carrier_id"] == carrier1.carrier_id
    assert data_c1["compliant_shipments"] == 1
    assert float(data_c1["carrier_payable_penalties_amount"]) == 0.0

    # 2. Carrier 2 (Carrier of label 2: breached, owes penalty)
    resp_c2 = await client.get("/api/v1/sla/carrier/metrics", headers={"X-API-Key": api_key_c2})
    assert resp_c2.status_code == 200
    data_c2 = resp_c2.json()
    assert data_c2["carrier_id"] == carrier2.carrier_id
    assert data_c2["breached_shipments"] == 1
    assert float(data_c2["carrier_payable_penalties_amount"]) == 20000.0

    # Carrier 2 shipments
    resp_s2 = await client.get("/api/v1/sla/carrier/shipments", headers={"X-API-Key": api_key_c2})
    assert resp_s2.status_code == 200
    assert resp_s2.json()["total"] == 1
    assert resp_s2.json()["items"][0]["tracking_number"] == label2.tracking_number
    assert resp_s2.json()["items"][0]["is_carrier_payable"] is True


# =============================================================================
# Work Package 2: Analytical Data Model, ETL Pipeline, Lineage & Data Quality
# =============================================================================


@pytest.mark.asyncio
async def test_analytical_star_schema_etl_execution_and_lineage(db_session: AsyncSession):
    """Test full ETL pipeline: sync dimensions, load facts with surrogate keys, and track batch lineage."""
    await _seed_test_data(db_session)
    await db_session.commit()

    service = AnalyticalEtlService()

    # Run ETL pipeline
    batch = await service.run_etl_pipeline(db_session, pipeline_name="test_pipeline_run")
    await db_session.commit()

    # 1. Verify Batch Run Audit & Lineage
    assert batch.status == "COMPLETED"
    assert batch.records_extracted >= 2
    assert batch.records_loaded >= 2
    assert batch.records_rejected == 0
    assert batch.completed_at is not None

    # 2. Verify Dimensions
    dim_dates = (await db_session.execute(select(DimDate))).scalars().all()
    assert len(dim_dates) >= 365  # Multi-year calendar populated

    dim_brands = (await db_session.execute(select(DimBrand))).scalars().all()
    assert len(dim_brands) >= 2

    dim_carriers = (await db_session.execute(select(DimCarrier))).scalars().all()
    assert len(dim_carriers) >= 2

    dim_dcs = (await db_session.execute(select(DimDistributionCenter))).scalars().all()
    assert len(dim_dcs) >= 1

    dim_statuses = (await db_session.execute(select(DimShipmentStatus))).scalars().all()
    status_codes = {s.status_code for s in dim_statuses}
    assert {
        "CREATED",
        "DISPATCHED",
        "IN_TRANSIT",
        "OUT_FOR_DELIVERY",
        "EXCEPTION",
        "DELIVERED",
    }.issubset(status_codes)

    dim_geos = (await db_session.execute(select(DimGeography))).scalars().all()
    assert len(dim_geos) >= 2

    # 3. Verify FactShipmentSla Grain and Measures (1 row per label_id)
    facts_sla = (await db_session.execute(select(FactShipmentSla))).scalars().all()
    assert len(facts_sla) == 2
    for fact in facts_sla:
        assert fact.brand_key is not None
        assert fact.carrier_key is not None
        assert fact.dc_key is not None
        assert fact.geo_key is not None
        assert fact.status_key is not None
        assert fact.etl_batch_id == batch.batch_id  # Traceable lineage
        assert fact.source_system == "operational_db"

    # 4. Verify FactFinancialPenalty
    facts_penalty = (await db_session.execute(select(FactFinancialPenalty))).scalars().all()
    assert len(facts_penalty) >= 1
    penalty_fact = facts_penalty[0]
    assert penalty_fact.calculation_date_key is not None
    assert penalty_fact.brand_key is not None
    assert penalty_fact.carrier_key is not None
    assert penalty_fact.freight_amount == Decimal("200000.00")
    assert penalty_fact.penalty_amount == Decimal("20000.00")
    assert penalty_fact.etl_batch_id == batch.batch_id


@pytest.mark.asyncio
async def test_analytical_data_quality_and_rejected_records(db_session: AsyncSession):
    """Test that orphan/corrupted records are captured in etl_rejected_records rather than silently discarded."""
    service = AnalyticalEtlService()

    # Create an orphan label referencing a non-existent order
    orphan_label = ShippingLabel(
        order_id=999999999,  # Non-existent order
        carrier_id=1,
        tracking_number="TRK-ORPHAN-ERR",
        status="IN_TRANSIT",
    )
    db_session.add(orphan_label)
    await db_session.flush()

    batch = await service.run_etl_pipeline(db_session, pipeline_name="test_rejection_pipeline")
    await db_session.commit()

    assert batch.records_rejected >= 1

    # Check rejected records table
    stmt_rej = select(EtlRejectedRecord).where(EtlRejectedRecord.batch_id == batch.batch_id)
    res_rej = await db_session.execute(stmt_rej)
    rejected_rows = res_rej.scalars().all()
    assert len(rejected_rows) >= 1
    rejection = rejected_rows[0]
    assert rejection.source_table == "shipping_labels"
    assert "Orphan shipping label" in rejection.rejection_reason


@pytest.mark.asyncio
async def test_analytics_api_endpoints(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    """Test Analytics API endpoints: triggering ETL, querying batches, facts, and aggregated KPIs."""
    await _seed_test_data(db_session)
    await db_session.commit()

    admin_token = "admin_super_secret_token_32_chars"
    api_key = "standard_api_key_32_characters_ok"
    monkeypatch.setattr(settings, "admin_api_key", admin_token)
    monkeypatch.setattr(settings, "api_key", api_key)

    # 1. Trigger ETL run via POST /api/v1/analytics/etl/run
    resp_run = await client.post(
        "/api/v1/analytics/etl/run",
        headers={"X-Admin-Token": admin_token},
    )
    assert resp_run.status_code == 200
    batch_data = resp_run.json()
    assert batch_data["status"] == "COMPLETED"

    # 2. Audit ETL batches via GET /api/v1/analytics/etl/batches
    resp_batches = await client.get(
        "/api/v1/analytics/etl/batches",
        headers={"X-Admin-Token": admin_token},
    )
    assert resp_batches.status_code == 200
    assert len(resp_batches.json()) >= 1

    # 3. Query Fact Shipments SLA via GET /api/v1/analytics/facts/shipments-sla
    resp_facts = await client.get(
        "/api/v1/analytics/facts/shipments-sla",
        headers={"X-API-Key": api_key},
    )
    assert resp_facts.status_code == 200
    facts_data = resp_facts.json()
    assert len(facts_data) == 2

    # 4. Query Fact Financial Penalties via GET /api/v1/analytics/facts/penalties
    resp_p_facts = await client.get(
        "/api/v1/analytics/facts/penalties",
        headers={"X-API-Key": api_key},
    )
    assert resp_p_facts.status_code == 200
    assert len(resp_p_facts.json()) >= 1

    # 5. Query KPI summary via GET /api/v1/analytics/kpis
    resp_kpi = await client.get(
        "/api/v1/analytics/kpis",
        headers={"X-API-Key": api_key},
    )
    assert resp_kpi.status_code == 200
    kpi_data = resp_kpi.json()
    assert kpi_data["total_shipments"] == 2
    assert kpi_data["compliant_shipments"] == 1
    assert kpi_data["breached_shipments"] == 1
    assert float(kpi_data["compliance_rate_pct"]) == 50.0
    assert float(kpi_data["total_freight_volume"]) == 350000.0  # 150k + 200k
    assert float(kpi_data["total_penalties_amount"]) == 20000.0
