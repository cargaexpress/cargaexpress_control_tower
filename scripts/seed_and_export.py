import asyncio
import os
import sys
import csv
from urllib.parse import quote_plus
from datetime import datetime, UTC, date, timedelta
from decimal import Decimal

backend_dir = os.path.abspath("backend")
sys.path.insert(0, backend_dir)

db_user = "cargaexpress_admin"
db_pass = "1<)dNjqy_W:sgTA<%rd6p#YB"
db_host = "127.0.0.1"
db_port = "5453"
db_name = "cargaexpress_staging"

encoded_pass = quote_plus(db_pass)
async_db_url = f"postgresql+asyncpg://{db_user}:{encoded_pass}@{db_host}:{db_port}/{db_name}"

os.environ["DATABASE_URL"] = async_db_url
os.environ["APP_ENV"] = "staging"

print("=" * 70)
print("1. POPULATING OPERATIONAL & ANALYTICAL DATA ON RDS")
print("=" * 70)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.distribution_center import DistributionCenter
from app.models.shipment_type import ShipmentType
from app.models.order import Order
from app.models.dispatch import Dispatch
from app.models.shipping_label import ShippingLabel
from app.models.financial import UniversalPenaltyConfig
from app.services.sla_engine import SlaEngineService
from app.services.financial_engine import FinancialEngineService
from app.services.analytical_etl import AnalyticalEtlService

engine = create_async_engine(async_db_url)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def populate():
    async with async_session() as db:
        # Check distribution centers
        res = await db.execute(select(DistributionCenter))
        dc = res.scalars().first()
        if not dc:
            dc = DistributionCenter(
                code="DC-BOG-01", name="Bogota Central Hub", city="Bogota", country_code="CO"
            )
            db.add(dc)
            await db.flush()

        # Check shipment types
        res = await db.execute(select(ShipmentType))
        st = res.scalars().first()
        if not st:
            st = ShipmentType(shipment_type_code="STANDARD", description="Standard Ground Delivery")
            db.add(st)
            await db.flush()

        # Check brands
        res = await db.execute(select(Brand))
        brands = res.scalars().all()
        if len(brands) == 0:
            b1 = Brand(name="ElectroHogar Colombia", tier="TIER_1", is_active=True)
            b2 = Brand(name="ModaFashion Retail", tier="TIER_2", is_active=True)
            b3 = Brand(name="TechGadgets Global", tier="TIER_1", is_active=True)
            db.add_all([b1, b2, b3])
            await db.flush()
            brands = [b1, b2, b3]

        # Check carriers
        res = await db.execute(select(Carrier))
        carriers = res.scalars().all()
        print(f"Available carriers in DB: {len(carriers)}")

        # Check universal penalty configs
        res = await db.execute(select(UniversalPenaltyConfig))
        pen_cfg = res.scalars().first()
        if not pen_cfg:
            pen_cfg = UniversalPenaltyConfig(
                version="v1.0",
                delay_level="LOW",
                min_delay_days=1,
                max_delay_days=5,
                penalty_percentage=Decimal("10.00"),
                maximum_cap_percentage=Decimal("20.00"),
                effective_date=date.today() - timedelta(days=30),
                is_active=True,
                approval_status="APPROVED",
            )
            db.add(pen_cfg)
            await db.flush()

        # Seed realistic orders, dispatches, labels, SLAs, penalties
        now = datetime.now(UTC)
        sla_engine = SlaEngineService()
        fin_engine = FinancialEngineService(sla_engine=sla_engine)

        res = await db.execute(select(Order))
        existing_orders = res.scalars().all()
        if len(existing_orders) < 20:
            print("Seeding 25 operational orders and shipments across carriers...")
            for i in range(1, 26):
                brand = brands[i % len(brands)]
                carrier = carriers[i % len(carriers)]
                order_dt = now - timedelta(days=(i % 10) + 1, hours=i)
                disp_dt = order_dt + timedelta(hours=3)

                order = Order(
                    brand_id=brand.brand_id,
                    dc_id=dc.dc_id,
                    shipment_type_code="STANDARD",
                    brand_order_ref=f"ORD-B{brand.brand_id}-{i:04d}",
                    destination_country="CO",
                    destination_region="ANDINA" if i % 2 == 0 else "CARIBE",
                    freight_value=Decimal("120000.00") + Decimal(i * 4500),
                    status="DELIVERED" if i % 3 != 0 else "IN_TRANSIT",
                )
                order.created_at = order_dt
                db.add(order)
                await db.flush()

                disp = Dispatch(
                    dc_id=dc.dc_id, carrier_id=carrier.carrier_id, dispatched_at=disp_dt
                )
                db.add(disp)
                await db.flush()

                label = ShippingLabel(
                    order_id=order.order_id,
                    carrier_id=carrier.carrier_id,
                    tracking_number=f"TRK-2026-{carrier.carrier_id:02d}-{i:04d}",
                    dispatch_id=disp.dispatch_id,
                    status="DELIVERED" if i % 3 != 0 else "IN_TRANSIT",
                )
                label.created_at = disp_dt
                db.add(label)
                await db.flush()

                # Evaluate SLA
                if i % 4 == 0:
                    # Breached shipment (delivered late)
                    delivery_dt = disp_dt + timedelta(days=5)
                    label.status = "DELIVERED"
                    await sla_engine.evaluate_shipment_sla(db, label, current_time_utc=delivery_dt)
                    await fin_engine.calculate_freight_penalty(
                        db, label, current_time_utc=delivery_dt, config_version="v1.0"
                    )
                elif i % 3 != 0:
                    # Compliant shipment (delivered on time)
                    delivery_dt = disp_dt + timedelta(days=1, hours=12)
                    label.status = "DELIVERED"
                    await sla_engine.evaluate_shipment_sla(db, label, current_time_utc=delivery_dt)
                else:
                    # Active in transit
                    await sla_engine.evaluate_shipment_sla(db, label, current_time_utc=now)

            await db.commit()
            print("[OK] Seeded 25 realistic orders, labels, SLAs, and penalties!")

        # Execute Analytical ETL Service
        print("Running Analytical ETL Service...")
        etl = AnalyticalEtlService(sla_engine=sla_engine)
        batch = await etl.run_etl_pipeline(db)
        await db.commit()
        print(f"[OK] Analytical ETL Batch {batch.batch_id} completed: records_loaded={batch.records_loaded}, status={batch.status}")

asyncio.run(populate())

print("=" * 70)
print("2. DUMPING 8 OLAP TABLES TO CSV")
print("=" * 70)

import asyncpg

tables = [
    "dim_dates",
    "dim_brands",
    "dim_carriers",
    "dim_distribution_centers",
    "dim_geographies",
    "dim_shipment_statuses",
    "fact_shipments_sla",
    "fact_financial_penalties"
]

export_dir = os.path.join(os.environ.get("TEMP", "."), "olap_export")
os.makedirs(export_dir, exist_ok=True)

async def dump_csv():
    conn = await asyncpg.connect(
        user=db_user,
        password=db_pass,
        database=db_name,
        host=db_host,
        port=db_port
    )
    for tbl in tables:
        rows = await conn.fetch(f"SELECT * FROM {tbl}")
        csv_path = os.path.join(export_dir, f"{tbl}.csv")
        if rows:
            keys = list(rows[0].keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(keys)
                for r in rows:
                    writer.writerow([r[k] for k in keys])
        else:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                pass
        print(f"Dumped {tbl}: {len(rows)} rows to {csv_path}")
    await conn.close()

asyncio.run(dump_csv())
print(f"[OK] All 8 tables dumped to {export_dir}")
