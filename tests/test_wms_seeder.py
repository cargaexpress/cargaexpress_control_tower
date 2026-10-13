"""Pruebas unitarias para el Seeder idempotente de WMS y Transportadoras."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, func

from app.database import Base
from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.order import Order
from app.models.shipping_label import ShippingLabel
from app.models.state_mapping import StateMapping
from simulators.seed.seed_wms import SeedConfig, WMSSeeder
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import BigInteger


@compiles(BigInteger, "sqlite")
def compile_big_int_sqlite(element, compiler, **kw):
    return "INTEGER"


@pytest_asyncio.fixture
async def async_db_session():
    """Crea una base de datos SQLite en memoria para probar el seed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as session:
        yield session

    await engine.dispose()



@pytest.mark.asyncio
async def test_wms_seeder_initial_population(async_db_session: AsyncSession):
    """Verifica que el seeder popule correctamente todas las tablas base y pedidos."""
    config = SeedConfig(seed=42, orders_count=10, carriers_to_seed=[1, 2, 3])
    seeder = WMSSeeder(session=async_db_session, config=config)

    result = await seeder.execute_full_seed()
    assert result["status"] == "success"
    assert result["shipment_types_count"] == 3
    assert result["distribution_centers_count"] == 3
    assert result["brands_count"] == 3
    assert result["carriers_count"] == 3
    assert result["tracking_numbers_count"] == 10

    # Comprobar registros en base de datos
    brands_count = await async_db_session.scalar(select(func.count(Brand.brand_id)))
    assert brands_count == 3

    carriers_count = await async_db_session.scalar(select(func.count(Carrier.carrier_id)))
    assert carriers_count == 3

    orders_count = await async_db_session.scalar(select(func.count(Order.order_id)))
    assert orders_count == 10

    labels_count = await async_db_session.scalar(select(func.count(ShippingLabel.label_id)))
    assert labels_count == 10

    mappings_count = await async_db_session.scalar(select(func.count(StateMapping.id)))
    # Carrier 1 tiene 8 estados, Carrier 2 tiene 8 estados, Carrier 3 tiene 8 estados = 24
    assert mappings_count == 24


@pytest.mark.asyncio
async def test_wms_seeder_idempotency(async_db_session: AsyncSession):
    """Verifica que ejecutar el seeder dos veces consecutivas sea 100% idempotente (no duplique filas)."""
    config = SeedConfig(seed=42, orders_count=10, carriers_to_seed=[1, 2, 3])
    seeder = WMSSeeder(session=async_db_session, config=config)

    # Primera ejecución
    await seeder.execute_full_seed()

    # Segunda ejecución inmediata con la misma configuración
    await seeder.execute_full_seed()

    # Los conteos deben permanecer exactamente iguales
    brands_count = await async_db_session.scalar(select(func.count(Brand.brand_id)))
    assert brands_count == 3

    carriers_count = await async_db_session.scalar(select(func.count(Carrier.carrier_id)))
    assert carriers_count == 3

    orders_count = await async_db_session.scalar(select(func.count(Order.order_id)))
    assert orders_count == 10

    labels_count = await async_db_session.scalar(select(func.count(ShippingLabel.label_id)))
    assert labels_count == 10

    mappings_count = await async_db_session.scalar(select(func.count(StateMapping.id)))
    assert mappings_count == 24
