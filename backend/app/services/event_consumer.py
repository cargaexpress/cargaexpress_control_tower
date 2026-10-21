import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.exceptions import EntityNotFoundError
from app.services.normalization_service import NormalizationResult, normalize_and_apply_event
from app.services.rabbitmq_service import QueuedWebhookMessage

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
