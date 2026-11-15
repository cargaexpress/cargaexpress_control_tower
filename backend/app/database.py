from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=settings.sql_echo, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """Base declarative class from which all project ORM models inherit."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async database session per request and closes it on completion."""
    async with AsyncSessionLocal() as session:
        yield session


# =============================================================================
# Fallback & ORM Decoupling Gateway (Raw SQL / Vendor Independence Layer)
# =============================================================================


async def execute_raw_query(
    sql: str,
    params: dict[str, Any] | None = None,
    engine_override: AsyncEngine | None = None,
) -> list[dict[str, Any]]:
    """Execute parameterized raw SQL select query directly via connection pool.

    Bypasses ORM identity maps, model hydration, and unit-of-work abstractions.
    Returns list of column-to-value dictionaries.
    """
    active_engine = engine_override or engine
    async with active_engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]


async def execute_raw_scalar(
    sql: str,
    params: dict[str, Any] | None = None,
    engine_override: AsyncEngine | None = None,
) -> Any:
    """Execute raw SQL query and return a single scalar value."""
    active_engine = engine_override or engine
    async with active_engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return result.scalar()


async def execute_raw_command(
    sql: str,
    params: dict[str, Any] | None = None,
    engine_override: AsyncEngine | None = None,
) -> int:
    """Execute raw DML command (INSERT, UPDATE, DELETE) inside an isolated auto-committing transaction."""
    active_engine = engine_override or engine
    async with active_engine.begin() as conn:
        result = await conn.execute(text(sql), params or {})
        return result.rowcount or 0


async def execute_raw_transaction(
    statements: list[tuple[str, dict[str, Any] | None]],
    engine_override: AsyncEngine | None = None,
) -> list[int]:
    """Execute multiple raw SQL statements atomically within a single transaction.

    Automatically rolls back all statements if any exception occurs.
    """
    active_engine = engine_override or engine
    rowcounts: list[int] = []
    async with active_engine.begin() as conn:
        for sql, params in statements:
            result = await conn.execute(text(sql), params or {})
            rowcounts.append(result.rowcount or 0)
    return rowcounts


async def check_db_connectivity(engine_override: AsyncEngine | None = None) -> bool:
    """Verify underlying database engine connectivity independently of ORM models."""
    try:
        val = await execute_raw_scalar("SELECT 1", engine_override=engine_override)
        return val == 1
    except Exception:
        return False

