import asyncio
import json
import logging
from typing import Any

import aio_pika
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.exceptions import EntityNotFoundError
from app.services.normalization_service import NormalizationResult, normalize_and_apply_event
from app.services.rabbitmq_service import QueuedWebhookMessage, RabbitMQService

logger = logging.getLogger("cargaexpress.event_consumer")


async def process_queued_event(
    event_data: dict[str, Any] | QueuedWebhookMessage,
    db: AsyncSession,
) -> NormalizationResult:
    """Consumes an event message from `eventos_transportadora` and applies canonical normalization.

    Enforces business rules:
    - RN-01: Translates raw_status to canonical_status using cached mapping.
    - RN-02: Protects terminal states and writes to tracking_anomalies.
    - RN-07: Propagates order status when all shipping labels are delivered.
    """
    if isinstance(event_data, dict):
        msg = QueuedWebhookMessage.from_dict(event_data)
    else:
        msg = event_data

    logger.info(
        "Processing queued event %s for tracking %s (carrier %s)",
        msg.message_id,
        msg.tracking_number,
        msg.carrier_slug,
    )

    try:
        result = await normalize_and_apply_event(
            db=db,
            carrier_identifier=msg.carrier_slug,
            tracking_number=msg.tracking_number,
            raw_status=msg.raw_status,
            occurred_at=None,
            event_id=msg.event_id,
            location=msg.location,
        )
        return result
    except EntityNotFoundError as exc:
        logger.error(
            "Carrier '%s' not found while processing event %s: %s",
            msg.carrier_slug,
            msg.message_id,
            exc,
        )
        raise
    except Exception as exc:
        logger.exception(
            "Unexpected error processing event %s (tracking %s): %s",
            msg.message_id,
            msg.tracking_number,
            exc,
        )
        raise


def should_retry(retry_count: int) -> bool:
    """Check if message retry count is within configured maximum."""
    return retry_count < settings.rabbitmq_max_retries


async def handle_message(
    message: aio_pika.abc.AbstractIncomingMessage,
    session_factory: async_sessionmaker[AsyncSession] | Any = AsyncSessionLocal,
    channel: aio_pika.abc.AbstractChannel | None = None,
    exchange_name: str | None = None,
) -> bool:
    """Processes an incoming RabbitMQ message from `eventos_transportadora`.

    Acceptance Criteria:
    - The worker consumes messages, applies normalization, and sends an ACK only if processing is successful.
    - If processing fails, sends a NACK (or routes to retry queue if attempts remain).
    """
    msg_id = message.message_id or "unknown"
    headers = dict(message.headers or {})
    raw_retry = headers.get("retry_count", 0)
    try:
        retry_count = int(raw_retry) if isinstance(raw_retry, (int, float, str)) else 0
    except (ValueError, TypeError):
        retry_count = 0

    try:
        raw_body = message.body.decode("utf-8")
        event_dict = json.loads(raw_body)
    except Exception as parse_exc:
        logger.error("Message %s has unparseable payload: %s", msg_id, parse_exc)
        # Malformed payloads cannot be recovered by retrying; send NACK without requeue (moves to DLQ)
        await message.nack(requeue=False)
        return False

    try:
        async with session_factory() as session:
            result = await process_queued_event(event_dict, session)
            logger.info(
                "Event %s normalized successfully (tracking=%s, canonical=%s, anomaly=%s)",
                msg_id,
                result.tracking_number,
                result.canonical_status,
                result.is_anomaly,
            )

        # Processing succeeded: Send ACK
        await message.ack()
        logger.info("Message %s ACKed successfully.", msg_id)
        return True

    except Exception as exc:
        logger.exception("Failed to process event %s: %s", msg_id, exc)

        # Handle retry mechanism
        if should_retry(retry_count) and channel is not None:
            target_exchange = exchange_name or settings.rabbitmq_exchange
            next_retry = retry_count + 1
            try:
                exchange = await channel.get_exchange(target_exchange, ensure=False)
                retry_message = aio_pika.Message(
                    body=message.body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type=message.content_type or "application/json",
                    message_id=message.message_id,
                    headers={**headers, "retry_count": next_retry},
                )
                await exchange.publish(retry_message, routing_key="eventos.retry")
                logger.warning(
                    "Message %s forwarded to retry queue (attempt %d/%d).",
                    msg_id,
                    next_retry,
                    settings.rabbitmq_max_retries,
                )
                # ACK the original message so it doesn't block the main queue while in retry TTL
                await message.ack()
                return False
            except Exception as retry_exc:
                logger.error("Failed to forward message %s to retry queue: %s", msg_id, retry_exc)

        # Retries exhausted or no channel: NACK without requeue (routes to DLQ)
        await message.nack(requeue=False)
        logger.error(
            "Message %s NACKed without requeue (routed to DLQ after %d retries).",
            msg_id,
            retry_count,
        )
        return False


async def consume_events(
    rabbitmq_service: RabbitMQService,
    session_factory: Any = AsyncSessionLocal,
    max_messages: int | None = None,
    stop_event: asyncio.Event | None = None,
) -> int:
    """Continuously consumes and processes messages from `eventos_transportadora`.

    Returns the count of successfully processed and ACKed messages.
    """
    channel = await rabbitmq_service.get_channel()
    await channel.set_qos(prefetch_count=settings.rabbitmq_prefetch_count)
    topology = await rabbitmq_service.declare_topology()
    main_queue = topology.main_queue

    processed_count = 0
    logger.info(
        "Worker listening on queue '%s' (prefetch=%d)...",
        settings.rabbitmq_queue,
        settings.rabbitmq_prefetch_count,
    )

    async with main_queue.iterator() as queue_iter:
        async for message in queue_iter:
            success = await handle_message(
                message=message,
                session_factory=session_factory,
                channel=channel,
                exchange_name=settings.rabbitmq_exchange,
            )
            if success:
                processed_count += 1

            if max_messages is not None and processed_count >= max_messages:
                logger.info("Reached target max_messages (%d). Stopping consumer.", max_messages)
                break

            if stop_event is not None and stop_event.is_set():
                logger.info("Stop event received. Exiting consumer loop.")
                break

    return processed_count
