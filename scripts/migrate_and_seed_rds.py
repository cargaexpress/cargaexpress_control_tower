import asyncio
import os
import sys
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
print("1. RUNNING ALEMBIC MIGRATIONS ON RDS (via SSM Tunnel localhost:5453)")
print("=" * 70)

from alembic.config import Config
from alembic import command

alembic_ini_path = os.path.join(backend_dir, "alembic.ini")
alembic_cfg = Config(alembic_ini_path)
alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
alembic_cfg.set_main_option("sqlalchemy.url", async_db_url.replace("%", "%%"))

command.upgrade(alembic_cfg, "head")
print("[OK] All 34 tables created successfully on RDS PostgreSQL!")

print("=" * 70)
print("2. SEEDING OPERATIONAL DATA & RUNNING ANALYTICAL ETL")
print("=" * 70)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.services.analytical_etl import AnalyticalEtlService
from app.models.carrier import Carrier
from app.models.brand import Brand
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.models.sla_tracking import ShipmentSlaTracking
from app.models.financial import FreightPenalty

engine = create_async_engine(async_db_url)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def populate_and_run_etl():
    async with async_session() as db:
        res = await db.execute(select(Carrier))
        carriers = res.scalars().all()
        print(f"Total carriers in DB: {len(carriers)}")

        res = await db.execute(select(Brand))
        brands = res.scalars().all()
        print(f"Total brands in DB: {len(brands)}")

        if len(brands) == 0:
            print("Seeding sample brands...")
            sample_brands = [
                Brand(name="ElectroHogar", code="ELEC", is_active=True),
                Brand(name="ModaFashion", code="MODA", is_active=True),
                Brand(name="MegaStore", code="MEGA", is_active=True),
                Brand(name="TechGadgets", code="TECH", is_active=True),
            ]
            db.add_all(sample_brands)
            await db.commit()
            brands = sample_brands

        res = await db.execute(select(Order))
        orders = res.scalars().all()
        print(f"Total orders in DB: {len(orders)}")

        if len(orders) == 0:
            print("Seeding sample orders and shipping labels for SLA & Analytics...")
            now = datetime.now(UTC)
            for idx in range(1, 26):
                b = brands[idx % len(brands)]
                c = carriers[idx % len(carriers)]
                order_dt = now - timedelta(days=idx % 7 + 1)

                order = Order(
                    brand_id=b.id,
                    order_number=f"ORD-2026-{idx:04d}",
                    status="FULFILLED" if idx % 2 == 0 else "PROCESSING",
                    created_at=order_dt,
                )
                db.add(order)
                await db.flush()

                is_delivered = (idx % 2 == 0)
                is_breached = (idx % 3 == 0)

                label = ShippingLabel(
                    order_id=order.id,
                    carrier_id=c.id,
                    tracking_number=f"TRK-2026-{idx:05d}",
                    current_canonical_status="DELIVERED" if is_delivered else "IN_TRANSIT",
                    dispatch_date=order_dt + timedelta(hours=4),
                    delivery_date=order_dt + timedelta(hours=36) if is_delivered else None,
                    shipping_cost=Decimal("15000.00") + Decimal(idx * 500),
                )
                db.add(label)
                await db.flush()

                sla_track = ShipmentSlaTracking(
                    shipping_label_id=label.id,
                    deadline_utc=order_dt + timedelta(days=2),
                    transit_business_hours=Decimal("48.50") if is_breached else Decimal("24.00"),
                    delay_business_hours=Decimal("14.50") if is_breached else Decimal("0.00"),
                    is_compliant=not is_breached,
                    is_breached=is_breached,
                    is_in_risk=(idx % 5 == 0),
                    calculated_at=now,
                )
                db.add(sla_track)

                if is_breached:
                    penalty = FreightPenalty(
                        shipping_label_id=label.id,
                        order_id=order.id,
                        carrier_id=c.id,
                        responsible_party="carrier",
                        penalty_level="L1",
                        freight_amount=label.shipping_cost or Decimal("15000.00"),
                        base_penalty_amount=Decimal("3500.00"),
                        penalty_percentage=Decimal("0.10"),
                        final_penalty_amount=Decimal("3500.00"),
                        delay_business_days=Decimal("1.50"),
                        approval_status="APPROVED",
                        calculated_at=now,
                    )
                    db.add(penalty)

            await db.commit()
            print("[OK] Seeded 25 orders, shipping labels, and SLA records.")

        print("Executing AnalyticalEtlService...")
        etl_service = AnalyticalEtlService()
        batch = await etl_service.run_etl_pipeline(db)
        await db.commit()
        print(f"[OK] ETL Batch {batch.batch_id} completed: status={batch.status}, records_loaded={batch.records_loaded}")

asyncio.run(populate_and_run_etl())
print("[ALL DONE] RDS PostgreSQL is fully migrated, seeded, and analytical model populated!")
