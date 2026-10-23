# ruff: noqa: E402
import os

# Set default isolated values for test environment before instantiating settings/engine
# If neither TEST_DATABASE_URL nor DATABASE_URL is explicitly set (e.g. running locally without Docker),
# use sqlite+aiosqlite to allow frictionless local test runs.
# In CI (GitHub Actions), these variables are always explicitly defined pointing to PostgreSQL.
if not os.environ.get("TEST_DATABASE_URL") and not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_suite.db"
    os.environ["TEST_DATABASE_URL"] = "sqlite+aiosqlite:///test_suite.db"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.services.rabbitmq_service import QueuedWebhookMessage, get_rabbitmq_service


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):
    return "INTEGER"


class InMemoryRabbitMQService:
    """Mock in-memory RabbitMQ publisher for isolated, ultra-fast test runs."""

    def __init__(self) -> None:
        self.published_messages: list[QueuedWebhookMessage] = []

    async def publish_webhook_event(
        self, carrier_slug: str, event, content_type: str = "application/json"
    ) -> QueuedWebhookMessage:
        msg = QueuedWebhookMessage(
            message_id=f"msg-mock-{len(self.published_messages) + 1}",
            carrier_slug=carrier_slug,
            tracking_number=event.tracking_number,
            raw_status=event.raw_status,
            event_id=event.event_id,
            occurred_at=event.occurred_at.isoformat() if event.occurred_at else None,
            location=event.location,
            content_type=content_type,
            enqueued_at="2026-10-20T12:00:00Z",
            retry_count=0,
        )
        self.published_messages.append(msg)
        return msg


# Refuse to run against an unspecified DB, preventing tests from touching runtime data.
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
    """Prepare an isolated schema."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    """Keep test records independent across tests and reset identity sequences."""
    yield
    async with test_engine.begin() as conn:
        is_sqlite = "sqlite" in str(test_engine.url)
        for table in reversed(Base.metadata.sorted_tables):
            if is_sqlite:
                await conn.execute(text(f'DELETE FROM "{table.name}"'))
            else:
                await conn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))


@pytest_asyncio.fixture(autouse=True)
async def bind_cache_to_test_db(monkeypatch):
    """Ensure cache queries execute against the test database."""
    import app.services.state_mapping_cache as cache_module
    from app.services.state_mapping_cache import state_mapping_cache

    monkeypatch.setattr(cache_module, "AsyncSessionLocal", TestSessionLocal)
    state_mapping_cache.invalidate()
    yield
    state_mapping_cache.invalidate()


@pytest_asyncio.fixture(autouse=True)
async def default_mock_rabbitmq():
    """Inject in-memory RabbitMQ publisher for all API tests."""
    fake = InMemoryRabbitMQService()
    app.dependency_overrides[get_rabbitmq_service] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_rabbitmq_service, None)


@pytest_asyncio.fixture
async def db_session():
    """Direct a database session for tests to seed reference data (brand, dc, shipment_type)."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(monkeypatch):
    api_key = settings.api_key or "test-api-key"
    monkeypatch.setattr(settings, "brand_api_keys", {api_key: 1})
    default_headers = {
        "X-API-Key": api_key,
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=default_headers
    ) as ac:
        yield ac
