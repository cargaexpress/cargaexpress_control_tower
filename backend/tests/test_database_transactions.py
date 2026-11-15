"""Tests verifying database transaction semantics, commits, rollbacks, and ORM decoupling fallback."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import (
    check_db_connectivity,
    execute_raw_command,
    execute_raw_query,
    execute_raw_scalar,
    execute_raw_transaction,
)
from app.models.carrier import Carrier
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.shipment_type import ShipmentType
from tests.conftest import TestSessionLocal, test_engine


@pytest.mark.asyncio
async def test_orm_transaction_commit_persists_data(db_session: AsyncSession):
    """Verify that explicit commit persists entity changes across separate sessions."""
    carrier = Carrier(name="Carrier Commit Test", integration_type="TYPE_B", status="ACTIVE")
    db_session.add(carrier)
    await db_session.commit()
    carrier_id = carrier.carrier_id

    # Open a completely new session to verify cross-session persistence
    async with TestSessionLocal() as new_session:
        retrieved = await new_session.get(Carrier, carrier_id)
        assert retrieved is not None
        assert retrieved.name == "Carrier Commit Test"


@pytest.mark.asyncio
async def test_orm_transaction_rollback_reverts_uncommitted_state(db_session: AsyncSession):
    """Verify that uncommitted changes are discarded when rollback is called."""
    carrier = Carrier(name="Carrier Rollback Test", integration_type="TYPE_B", status="ACTIVE")
    db_session.add(carrier)
    await db_session.flush()
    carrier_id = carrier.carrier_id

    # Explicitly rollback before committing
    await db_session.rollback()

    async with TestSessionLocal() as new_session:
        retrieved = await new_session.get(Carrier, carrier_id)
        assert retrieved is None


@pytest.mark.asyncio
async def test_orm_transaction_rollback_on_integrity_error(db_session: AsyncSession):
    """Verify that integrity violations trigger clean rollback without leaving orphaned state."""
    carrier_1 = Carrier(name="Unique Carrier", integration_type="TYPE_B", status="ACTIVE")
    db_session.add(carrier_1)
    await db_session.commit()

    # Attempt to insert an order with invalid foreign keys to intentionally cause IntegrityError
    invalid_order = Order(
        brand_id=999999,  # Non-existent brand
        dc_id=999999,  # Non-existent DC
        shipment_type_code="STD",
        brand_order_ref="REF-FAIL-001",
        destination_country="CO",
        destination_region="Andina",
        freight_value=100.0,
        status="CREATED",
    )
    db_session.add(invalid_order)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()

    # Verify session is still healthy and operational after rollback
    healthy_query = await db_session.execute(select(Carrier).where(Carrier.name == "Unique Carrier"))
    assert healthy_query.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_raw_sql_decoupled_gateway():
    """Verify raw SQL execution operates independently of ORM model layer."""
    # Test connectivity check
    is_healthy = await check_db_connectivity(engine_override=test_engine)
    assert is_healthy is True

    # Test raw scalar
    scalar_result = await execute_raw_scalar("SELECT 42", engine_override=test_engine)
    assert scalar_result == 42

    # Insert test data using raw DML command
    rowcount = await execute_raw_command(
        'INSERT INTO carriers (name, integration_type, status) VALUES (:name, :type, :status)',
        {"name": "Raw Gateway Carrier", "type": "TYPE_B", "status": "ACTIVE"},
        engine_override=test_engine,
    )
    assert rowcount == 1

    # Query test data using raw query returning dictionaries
    rows = await execute_raw_query(
        'SELECT name, integration_type, status FROM carriers WHERE name = :name',
        {"name": "Raw Gateway Carrier"},
        engine_override=test_engine,
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "Raw Gateway Carrier"
    assert rows[0]["integration_type"] == "TYPE_B"


@pytest.mark.asyncio
async def test_raw_sql_atomic_transaction_rollback_on_failure():
    """Verify that multiple raw SQL statements execute atomically with automatic rollback."""
    # Seed one carrier
    await execute_raw_command(
        'INSERT INTO carriers (name, integration_type, status) VALUES (:name, :type, :status)',
        {"name": "Pre-existing Carrier", "type": "TYPE_B", "status": "ACTIVE"},
        engine_override=test_engine,
    )

    # Attempt a batch where the second statement has an invalid syntax / non-existent table
    failing_batch = [
        (
            'INSERT INTO carriers (name, integration_type, status) VALUES (:name, :type, :status)',
            {"name": "Batch Carrier 1", "type": "TYPE_B", "status": "ACTIVE"},
        ),
        (
            'INSERT INTO non_existent_table_xyz (col) VALUES (:val)',
            {"val": "will fail"},
        ),
    ]

    with pytest.raises(Exception):
        await execute_raw_transaction(failing_batch, engine_override=test_engine)

    # Assert that "Batch Carrier 1" was rolled back and does not exist
    rows = await execute_raw_query(
        'SELECT name FROM carriers WHERE name = :name',
        {"name": "Batch Carrier 1"},
        engine_override=test_engine,
    )
    assert len(rows) == 0
