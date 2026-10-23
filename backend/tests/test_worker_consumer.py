"""Tests for consumer worker process, ACK/NACK mechanics, and eventual normalization.

Meets Acceptance Criteria:
- The worker consumes messages, applies normalization, and sends an ACK only if processing is successful.
- Subtask 1: Create a separate worker process (consumer).
- Subtask 2: Connect the worker to the normalization service.
- Subtask 3: Implement ACK/NACK based on the processing result.
- Subtask 4: Test by publishing a sample message and verifying that it is eventually normalized.
"""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import aio_pika
import pytest
from sqlalchemy import select

from app.models.brand import Brand
from app.models.carrier import Carrier
from app.models.distribution_center import DistributionCenter
from app.models.order import Order
from app.models.order_line import OrderLine
from app.models.order_recipient import OrderRecipient
from app.models.shipment_type import ShipmentType
from app.models.shipping_label import ShippingLabel
from app.models.state_mapping import StateMapping
from app.services.event_consumer import (
    consume_events,
    handle_message,
)
from app.services.rabbitmq_service import RabbitMQService
from app.services.state_mapping_cache import state_mapping_cache


async def _seed_infrastructure(db_session):
    """Seed test brands, carriers, mappings, and order."""
    brand = Brand(brand_id=1, name="Test Brand", tier="standard", is_active=True)
    dc = DistributionCenter(dc_id=1, code="DC01", name="Main DC", city="Bogota", country_code="CO")
    shipment_type = ShipmentType(shipment_type_code="STD", description="Standard Delivery")
    carrier_alpha = Carrier(
        carrier_id=1, name="SimCarrier Alpha", integration_type="webhook", status="active"
    )
    db_session.add_all([brand, dc, shipment_type, carrier_alpha])
    await db_session.commit()

    mapping = StateMapping(
        id=1,
        carrier_id=carrier_alpha.carrier_id,
        raw_status="IN_TRANSIT",
        canonical_status="IN_TRANSIT",
    )
    db_session.add(mapping)
    await db_session.commit()
    state_mapping_cache.invalidate()

    order = Order(
        order_id=1,
        brand_id=brand.brand_id,
        dc_id=dc.dc_id,
        shipment_type_code=shipment_type.shipment_type_code,
        brand_order_ref="ORD-WORKER-001",
        destination_country="CO",
        destination_region="Cundinamarca",
        freight_value=Decimal("15000.00"),
        status="CREATED",
        order_lines=[
            OrderLine(order_line_id=1, order_id=1, line_number=1, sku="SKU-1", quantity_ordered=1)
        ],
        recipient=OrderRecipient(
            order_id=1,
            full_name="Cliente Test",
            address_line="Av 68 # 50-10",
            city="Bogota",
        ),
    )
    db_session.add(order)
    await db_session.commit()

    label = ShippingLabel(
        label_id=1,
        order_id=order.order_id,
        carrier_id=carrier_alpha.carrier_id,
        tracking_number="TRK-ALPHA-001",
        status="CREATED",
    )
    db_session.add(label)
    await db_session.commit()

    return {
        "carrier": carrier_alpha,
        "order": order,
        "label": label,
    }


@pytest.mark.asyncio
async def test_handle_message_success_sends_ack(db_session):
    """Subtask 2 & 3: Successful normalization results in message ACK."""
    await _seed_infrastructure(db_session)

    payload = {
        "message_id": "msg-succ-001",
        "carrier_slug": "alpha",
        "tracking_number": "TRK-ALPHA-001",
        "raw_status": "IN_TRANSIT",
        "event_id": "EVT-101",
        "occurred_at": "2026-10-20T10:00:00Z",
        "location": "Bogota Hub",
    }

    mock_message = AsyncMock(spec=aio_pika.abc.AbstractIncomingMessage)
    mock_message.message_id = "msg-succ-001"
    mock_message.body = json.dumps(payload).encode("utf-8")
    mock_message.headers = {"retry_count": 0}
    mock_message.ack = AsyncMock()
    mock_message.nack = AsyncMock()

    # Create dummy session factory yielding db_session
    class DummySessionFactory:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def __call__(self):
            return self

    success = await handle_message(
        message=mock_message,
        session_factory=DummySessionFactory(),
    )

    assert success is True
    # AC: sends an ACK only if processing is successful
    mock_message.ack.assert_awaited_once()
    mock_message.nack.assert_not_awaited()

    # Verify label normalized in database
    refreshed_label = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-ALPHA-001")
        )
    ).scalar_one()
    assert refreshed_label.status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_handle_message_malformed_json_sends_nack_without_requeue():
    """Subtask 3: Unparseable message payload sends NACK(requeue=False) to route to DLQ."""
    mock_message = AsyncMock(spec=aio_pika.abc.AbstractIncomingMessage)
    mock_message.message_id = "msg-bad-001"
    mock_message.body = b"NOT_VALID_JSON{{"
    mock_message.headers = {}
    mock_message.ack = AsyncMock()
    mock_message.nack = AsyncMock()

    success = await handle_message(message=mock_message)

    assert success is False
    # AC: Send NACK if processing fails
    mock_message.nack.assert_awaited_once_with(requeue=False)
    mock_message.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_retries_available_forwards_to_retry_queue():
    """Subtask 3: Transient failure forwards message to retry queue with incremented count."""
    payload = {
        "message_id": "msg-retry-001",
        "carrier_slug": "non_existent_carrier_slug",
        "tracking_number": "TRK-GHOST-123",
        "raw_status": "IN_TRANSIT",
    }

    mock_message = AsyncMock(spec=aio_pika.abc.AbstractIncomingMessage)
    mock_message.message_id = "msg-retry-001"
    mock_message.body = json.dumps(payload).encode("utf-8")
    mock_message.headers = {"retry_count": 1}
    mock_message.content_type = "application/json"
    mock_message.ack = AsyncMock()
    mock_message.nack = AsyncMock()

    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_channel.get_exchange.return_value = mock_exchange

    class FailingSessionFactory:
        async def __aenter__(self):
            raise ConnectionError("Simulated temporary database timeout")

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def __call__(self):
            return self

    success = await handle_message(
        message=mock_message,
        session_factory=FailingSessionFactory(),
        channel=mock_channel,
        exchange_name="eventos_exchange",
    )

    assert success is False
    # Forwarded to retry queue
    mock_exchange.publish.assert_awaited_once()
    call_args = mock_exchange.publish.call_args
    published_msg = call_args[0][0]
    routing_key = call_args[1]["routing_key"]
    assert routing_key == "eventos.retry"
    assert published_msg.headers["retry_count"] == 2

    # Original message ACKed so it leaves main queue while in retry TTL
    mock_message.ack.assert_awaited_once()
    mock_message.nack.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_retries_exhausted_sends_nack_to_dlq():
    """Subtask 3: When max retries are exhausted, send NACK(requeue=False) to DLQ."""
    payload = {
        "message_id": "msg-exhausted-001",
        "carrier_slug": "unknown_carrier",
        "tracking_number": "TRK-FAIL-999",
        "raw_status": "IN_TRANSIT",
    }

    mock_message = AsyncMock(spec=aio_pika.abc.AbstractIncomingMessage)
    mock_message.message_id = "msg-exhausted-001"
    mock_message.body = json.dumps(payload).encode("utf-8")
    # Retries already at max
    mock_message.headers = {"retry_count": 3}
    mock_message.ack = AsyncMock()
    mock_message.nack = AsyncMock()

    class FailingSessionFactory:
        async def __aenter__(self):
            raise RuntimeError("Fatal database crash")

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def __call__(self):
            return self

    success = await handle_message(
        message=mock_message,
        session_factory=FailingSessionFactory(),
    )

    assert success is False
    # AC: sends a NACK if processing fails
    mock_message.nack.assert_awaited_once_with(requeue=False)
    mock_message.ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_consume_events_processes_batch_and_stops():
    """Subtask 1: Consumer loop processes incoming messages and respects max_messages."""
    mock_service = AsyncMock(spec=RabbitMQService)
    mock_channel = AsyncMock()
    mock_queue = MagicMock()
    mock_service.get_channel.return_value = mock_channel

    class MockTopology:
        main_queue = mock_queue

    mock_service.declare_topology.return_value = MockTopology()

    # Create 2 mock messages
    msg1 = AsyncMock(spec=aio_pika.abc.AbstractIncomingMessage)
    msg1.message_id = "m1"
    msg1.body = json.dumps(
        {"carrier_slug": "alpha", "tracking_number": "T1", "raw_status": "ST"}
    ).encode()
    msg1.headers = {}
    msg1.ack = AsyncMock()
    msg1.nack = AsyncMock()

    msg2 = AsyncMock(spec=aio_pika.abc.AbstractIncomingMessage)
    msg2.message_id = "m2"
    msg2.body = json.dumps(
        {"carrier_slug": "alpha", "tracking_number": "T2", "raw_status": "ST"}
    ).encode()
    msg2.headers = {}
    msg2.ack = AsyncMock()
    msg2.nack = AsyncMock()

    # Generator simulating queue.iterator()
    async def async_msg_generator():
        for m in [msg1, msg2]:
            yield m

    class MockQueueIterator:
        async def __aenter__(self):
            return async_msg_generator()

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_queue.iterator = MagicMock(return_value=MockQueueIterator())

    # Mock process_queued_event
    from unittest.mock import patch

    with patch("app.services.event_consumer.process_queued_event", new=AsyncMock()):
        count = await consume_events(
            rabbitmq_service=mock_service,
            max_messages=2,
        )

    assert count == 2
    mock_channel.set_qos.assert_awaited_once()
    msg1.ack.assert_awaited_once()
    msg2.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_e2e_eventual_normalization(client, db_session, default_mock_rabbitmq):
    """Subtask 4: Publish a sample message to webhook and verify worker eventually normalizes it."""
    await _seed_infrastructure(db_session)

    # 1. Carrier posts webhook
    payload = {
        "event_id": "EVT-E2E-999",
        "tracking_number": "TRK-ALPHA-001",
        "status": "IN_TRANSIT",
        "occurred_at": "2026-10-20T11:00:00Z",
        "location": "Hub Central",
    }
    response = await client.post("/api/v1/webhooks/alpha", json=payload)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"

    # 2. Worker consumes message from queue
    assert len(default_mock_rabbitmq.published_messages) == 1
    queued_item = default_mock_rabbitmq.published_messages[-1]

    mock_msg = AsyncMock(spec=aio_pika.abc.AbstractIncomingMessage)
    mock_msg.message_id = queued_item.message_id
    mock_msg.body = queued_item.to_bytes()
    mock_msg.headers = {"retry_count": 0}
    mock_msg.ack = AsyncMock()
    mock_msg.nack = AsyncMock()

    class DummySessionFactory:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        def __call__(self):
            return self

    # 3. Worker handles message
    success = await handle_message(
        message=mock_msg,
        session_factory=DummySessionFactory(),
    )

    # 4. Verify ACK and eventual normalization in database
    assert success is True
    mock_msg.ack.assert_awaited_once()
    mock_msg.nack.assert_not_awaited()

    refreshed_label = (
        await db_session.execute(
            select(ShippingLabel).where(ShippingLabel.tracking_number == "TRK-ALPHA-001")
        )
    ).scalar_one()
    assert refreshed_label.status == "IN_TRANSIT"


@pytest.mark.asyncio
async def test_worker_main_runs_and_cancels_cleanly():
    """Test app.worker.main entry point executes and cleans up on cancellation."""
    import asyncio
    from unittest.mock import patch

    from app.worker import main

    with patch("app.worker.consume_events", side_effect=asyncio.CancelledError):
        # Should catch CancelledError and terminate cleanly without throwing
        await main()
