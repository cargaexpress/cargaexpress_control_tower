import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app

# Refuse to run against an unspecified DB, preventing tests from touching runtime data.
# Exige una BD explícita para evitar que los tests modifiquen datos de ejecución.
if not settings.test_database_url:
    raise RuntimeError("TEST_DATABASE_URL must point to an isolated test database")

test_engine = create_async_engine(settings.test_database_url)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    """Prepare an isolated schema.

    Prepara un esquema aislado.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    """Keep test records independent.

    Aísla los datos entre pruebas.
    """
    yield
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture(autouse=True)
async def bind_cache_to_test_db(monkeypatch):
    """Ensure cache queries execute against test database."""
    import app.services.state_mapping_cache as cache_module
    from app.services.state_mapping_cache import state_mapping_cache

    monkeypatch.setattr(cache_module, "AsyncSessionLocal", TestSessionLocal)
    state_mapping_cache.invalidate()
    yield
    state_mapping_cache.invalidate()


@pytest_asyncio.fixture
async def db_session():
    """Sesión directa para que los tests siembren datos de referencia (brand, dc, shipment_type)."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
