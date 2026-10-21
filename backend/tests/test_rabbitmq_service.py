"""Unit tests for RabbitMQ topology, message serialization, and publishing service."""

import json
from unittest.mock import AsyncMock

import aio_pika
import pytest

from app.services.event_consumer import process_queued_event, should_retry
from app.services.exceptions import EntityNotFoundError
from app.services.rabbitmq_service import (
    QueuedWebhookMessage,
    RabbitMQService,
)
from app.services.webhook_decoders import DecodedWebhookEvent


def test_queued_webhook_message_serialization():
    msg = QueuedWebhookMessage(
        message_id="msg-123",
        carrier_slug="simcarrier-alpha",
        tracking_number="TRK-999",
        raw_status="IN_TRANSIT",
        event_id="evt-001",
        occurred_at="2026-03-29T10:00:00Z",
        location="Bogota Hub",
        content_type="application/json",
        enqueued_at="2026-03-29T10:00:01Z",
        retry_count=1,
    )

    data = msg.to_dict()
    assert data["message_id"] == "msg-123"
    assert data["carrier_slug"] == "simcarrier-alpha"
    assert data["retry_count"] == 1

    msg_bytes = msg.to_bytes()
    assert isinstance(msg_bytes, bytes)
    parsed_json = json.loads(msg_bytes.decode("utf-8"))
    assert parsed_json["tracking_number"] == "TRK-999"

    reconstructed = QueuedWebhookMessage.from_dict(data)
    assert reconstructed.message_id == msg.message_id
    assert reconstructed.tracking_number == msg.tracking_number
    assert reconstructed.location == "Bogota Hub"


def test_should_retry_logic():
    assert should_retry(0) is True
    assert should_retry(1) is True
    assert should_retry(2) is True
    assert should_retry(3) is False
    assert should_retry(5) is False


@pytest.mark.asyncio
async def test_declare_topology_creates_exchanges_and_queues():
    """Subtask 2: Verify exchanges, main queue, retry queue (TTL), and DLQ."""
    service = RabbitMQService(
        exchange_name="test_exchange",
        main_queue="test_queue",
        retry_queue="test_queue.retry",
        dlq_queue="test_queue.dlq",
        retry_ttl_ms=3000,
    )

    mock_channel = AsyncMock(spec=aio_pika.abc.AbstractChannel)
    mock_channel.is_closed = False
    service._channel = mock_channel

    mock_exchange = AsyncMock(spec=aio_pika.abc.AbstractExchange)
    mock_main_q = AsyncMock(spec=aio_pika.abc.AbstractQueue)
    mock_retry_q = AsyncMock(spec=aio_pika.abc.AbstractQueue)
    mock_dlq = AsyncMock(spec=aio_pika.abc.AbstractQueue)

    mock_channel.declare_exchange.return_value = mock_exchange
    mock_channel.declare_queue.side_effect = [mock_dlq, mock_retry_q, mock_main_q]

    topology = await service.declare_topology()

    # 1. Exchange
    mock_channel.declare_exchange.assert_called_once_with(
        "test_exchange",
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )

    # 2. DLQ Queue
    mock_dlq.bind.assert_called_once_with(mock_exchange, routing_key="eventos.dlq")

    # 3. Retry Queue with TTL arguments
    mock_channel.declare_queue.assert_any_call(
        "test_queue.retry",
        durable=True,
        arguments={
            "x-message-ttl": 3000,
            "x-dead-letter-exchange": "test_exchange",
            "x-dead-letter-routing-key": "eventos.transportadora",
        },
    )
    mock_retry_q.bind.assert_called_once_with(mock_exchange, routing_key="eventos.retry")

    # 4. Main Queue with DLQ arguments
    mock_channel.declare_queue.assert_any_call(
        "test_queue",
        durable=True,
        arguments={
            "x-dead-letter-exchange": "test_exchange",
            "x-dead-letter-routing-key": "eventos.dlq",
        },
    )
    assert topology.exchange == mock_exchange
    assert topology.main_queue == mock_main_q
    assert topology.retry_queue == mock_retry_q
    assert topology.dlq_queue == mock_dlq


@pytest.mark.asyncio
async def test_publish_webhook_event_publishes_persistent_message():
    """Subtask 3: Verify publishing decoded event with delivery_mode=PERSISTENT."""
    service = RabbitMQService(exchange_name="test_exchange")

    mock_channel = AsyncMock(spec=aio_pika.abc.AbstractChannel)
    mock_channel.is_closed = False
    service._channel = mock_channel

    mock_exchange = AsyncMock(spec=aio_pika.abc.AbstractExchange)
    mock_channel.get_exchange.return_value = mock_exchange

    decoded_event = DecodedWebhookEvent(
        event_id="evt-100",
        tracking_number="TRK-100",
        raw_status="OUT_FOR_DELIVERY",
        occurred_at=None,
        location="Cali",
    )

    queued_msg = await service.publish_webhook_event(
        carrier_slug="gamma",
        event=decoded_event,
        content_type="application/json",
    )

    assert queued_msg.tracking_number == "TRK-100"
    assert queued_msg.carrier_slug == "gamma"
    assert queued_msg.raw_status == "OUT_FOR_DELIVERY"
    assert queued_msg.location == "Cali"

    mock_exchange.publish.assert_called_once()
    published_call = mock_exchange.publish.call_args
    message = published_call[0][0]
    routing_key = published_call[1]["routing_key"]

    assert routing_key == "eventos.transportadora"
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert message.content_type == "application/json"
    assert message.headers["carrier"] == "gamma"
    assert message.headers["tracking_number"] == "TRK-100"


@pytest.mark.asyncio
async def test_close_handles_open_and_closed_connections():
    service = RabbitMQService()
    mock_conn = AsyncMock()
    mock_conn.is_closed = False
    mock_channel = AsyncMock()
    mock_channel.is_closed = False

    service._connection = mock_conn
    service._channel = mock_channel

    await service.close()

    mock_channel.close.assert_called_once()
    mock_conn.close.assert_called_once()
    assert service._channel is None
    assert service._connection is None


@pytest.mark.asyncio
async def test_process_queued_event_calls_normalization(monkeypatch):
    from app.services.normalization_service import NormalizationResult

    async def mock_normalize(*args, **kwargs):
        return NormalizationResult(
            success=True,
            carrier_id=1,
            tracking_number="TRK-OK",
            raw_status="DELIVERED",
            canonical_status="DELIVERED",
            previous_status="IN_TRANSIT",
            new_status="DELIVERED",
            is_anomaly=False,
            message="Processed",
        )

    monkeypatch.setattr(
        "app.services.event_consumer.normalize_and_apply_event",
        mock_normalize,
    )

    msg_dict = {
        "message_id": "m1",
        "carrier_slug": "alpha",
        "tracking_number": "TRK-OK",
        "raw_status": "DELIVERED",
    }
    mock_db = AsyncMock()
    result = await process_queued_event(msg_dict, mock_db)
    assert result.success is True
    assert result.canonical_status == "DELIVERED"


@pytest.mark.asyncio
async def test_process_queued_event_raises_entity_not_found(monkeypatch):
    async def mock_normalize(*args, **kwargs):
        raise EntityNotFoundError("carrier", "unknown-slug")

    monkeypatch.setattr(
        "app.services.event_consumer.normalize_and_apply_event",
        mock_normalize,
    )

    msg_dict = {
        "message_id": "m2",
        "carrier_slug": "unknown-slug",
        "tracking_number": "TRK-X",
        "raw_status": "ANY",
    }
    mock_db = AsyncMock()
    with pytest.raises(EntityNotFoundError):
        await process_queued_event(msg_dict, mock_db)
