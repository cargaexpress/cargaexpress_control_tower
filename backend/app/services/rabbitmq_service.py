import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import aio_pika
from aio_pika.abc import (
    AbstractChannel,
    AbstractConnection,
    AbstractExchange,
    AbstractQueue,
    DeliveryMode,
)

from app.config import settings
from app.services.webhook_decoders import DecodedWebhookEvent

logger = logging.getLogger("cargaexpress.rabbitmq")


@dataclass(slots=True)
class QueuedWebhookMessage:
    """Structure of an event message published to the broker."""

    message_id: str
    carrier_slug: str
    tracking_number: str
    raw_status: str
    event_id: str
    occurred_at: str | None
    location: str | None
    content_type: str
    enqueued_at: str
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_dict()).encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueuedWebhookMessage":
        return cls(
            message_id=data["message_id"],
            carrier_slug=data["carrier_slug"],
            tracking_number=data["tracking_number"],
            raw_status=data["raw_status"],
            event_id=data.get("event_id", ""),
            occurred_at=data.get("occurred_at"),
            location=data.get("location"),
            content_type=data.get("content_type", "application/json"),
            enqueued_at=data.get("enqueued_at", datetime.now(UTC).isoformat()),
            retry_count=data.get("retry_count", 0),
        )


@dataclass(slots=True)
class TopologyDeclarations:
    """Declared RabbitMQ infrastructure objects."""

    exchange: AbstractExchange
    main_queue: AbstractQueue
    retry_queue: AbstractQueue
    dlq_queue: AbstractQueue


class RabbitMQService:
    """Manages connection pooling, topology declaration, and event publishing for RabbitMQ.

    Topology Design (Subtask 2):
    - Exchange: `eventos_exchange` (Topic exchange, durable).
    - Main Queue: `eventos_transportadora` (Durable, dead-letters to `eventos.dlq`).
    - Retry Queue: `eventos_transportadora.retry` (Durable, message TTL, dead-letters back to `eventos.transportadora`).
    - DLQ: `eventos_transportadora.dlq` (Durable, stores failed/corrupt events for manual inspection).
    """

    def __init__(
        self,
        url: str | None = None,
        exchange_name: str | None = None,
        main_queue: str | None = None,
        retry_queue: str | None = None,
        dlq_queue: str | None = None,
        retry_ttl_ms: int | None = None,
    ) -> None:
        self.url = url or settings.rabbitmq_url
        self.exchange_name = exchange_name or settings.rabbitmq_exchange
        self.main_queue_name = main_queue or settings.rabbitmq_queue
        self.retry_queue_name = retry_queue or settings.rabbitmq_retry_queue
        self.dlq_queue_name = dlq_queue or settings.rabbitmq_dlq_queue
        self.retry_ttl_ms = retry_ttl_ms or settings.rabbitmq_retry_ttl_ms

        self._connection: AbstractConnection | None = None
        self._channel: AbstractChannel | None = None
        self._topology: TopologyDeclarations | None = None

    async def get_connection(self) -> AbstractConnection:
        """Establish or return an active connection."""
        if self._connection is None or self._connection.is_closed:
            self._connection = await aio_pika.connect_robust(self.url)
        return self._connection

    async def get_channel(self) -> AbstractChannel:
        """Establish or return an active channel."""
        if self._channel is None or self._channel.is_closed:
            conn = await self.get_connection()
            self._channel = await conn.channel()
            # Set publisher confirms for reliable delivery
            await self._channel.set_qos(prefetch_count=100)
        return self._channel

    async def declare_topology(self) -> TopologyDeclarations:
        """Declare exchanges, queues, DLQ, and retry queues according to Subtask 2."""
        channel = await self.get_channel()

        # 1. Exchange principal (Topic)
        exchange = await channel.declare_exchange(
            self.exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        # 2. Dead-Letter Queue (DLQ)
        # Recibe mensajes que agotaron reintentos o son irrecuperables
        dlq = await channel.declare_queue(
            self.dlq_queue_name,
            durable=True,
        )
        await dlq.bind(exchange, routing_key="eventos.dlq")

        # 3. Retry Queue con TTL
        # Retiene el mensaje durante `retry_ttl_ms` y al expirar lo re-enruta a la cola principal
        retry_queue = await channel.declare_queue(
            self.retry_queue_name,
            durable=True,
            arguments={
                "x-message-ttl": self.retry_ttl_ms,
                "x-dead-letter-exchange": self.exchange_name,
                "x-dead-letter-routing-key": "eventos.transportadora",
            },
        )
        await retry_queue.bind(exchange, routing_key="eventos.retry")

        # 4. Cola principal `eventos_transportadora`
        # Si un mensaje es rechazado sin requeue, viaja automáticamente al DLQ
        main_queue = await channel.declare_queue(
            self.main_queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": self.exchange_name,
                "x-dead-letter-routing-key": "eventos.dlq",
            },
        )
        await main_queue.bind(exchange, routing_key="eventos.transportadora")
        await main_queue.bind(exchange, routing_key="eventos.#")

        self._topology = TopologyDeclarations(
            exchange=exchange,
            main_queue=main_queue,
            retry_queue=retry_queue,
            dlq_queue=dlq,
        )
        return self._topology

    async def publish_webhook_event(
        self,
        carrier_slug: str,
        event: DecodedWebhookEvent,
        content_type: str = "application/json",
    ) -> QueuedWebhookMessage:
        """Serialize and publish decoded webhook event to `eventos_transportadora`.

        Guarantees sub-millisecond publishing latency complying with RNF-01 (< 200 ms).
        """
        message_id = str(uuid.uuid4())
        queued_msg = QueuedWebhookMessage(
            message_id=message_id,
            carrier_slug=carrier_slug,
            tracking_number=event.tracking_number,
            raw_status=event.raw_status,
            event_id=event.event_id,
            occurred_at=event.occurred_at.isoformat() if event.occurred_at else None,
            location=event.location,
            content_type=content_type,
            enqueued_at=datetime.now(UTC).isoformat(),
        )

        channel = await self.get_channel()
        exchange = await channel.get_exchange(self.exchange_name, ensure=False)

        message = aio_pika.Message(
            body=queued_msg.to_bytes(),
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=message_id,
            headers={
                "carrier": carrier_slug,
                "tracking_number": event.tracking_number,
                "retry_count": 0,
            },
        )

        await exchange.publish(
            message,
            routing_key="eventos.transportadora",
        )

        logger.info(
            "Event %s for tracking %s (carrier %s) published to queue",
            message_id,
            event.tracking_number,
            carrier_slug,
        )
        return queued_msg

    async def close(self) -> None:
        """Close channel and connection safely."""
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
            self._channel = None
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
            self._connection = None


# Singleton instance for dependency injection
rabbitmq_service = RabbitMQService()


async def get_rabbitmq_service() -> RabbitMQService:
    """FastAPI dependency for RabbitMQ service injection."""
    return rabbitmq_service
