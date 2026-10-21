import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.normalization_service import find_carrier_by_slug_or_id
from app.services.rabbitmq_service import (
    QueuedWebhookMessage,
    RabbitMQService,
    get_rabbitmq_service,
)
from app.services.webhook_decoders import WebhookDecodeError, decode_carrier_payload

logger = logging.getLogger("cargaexpress.webhooks")

router = APIRouter(tags=["webhooks"])


@router.post(
    "/api/v1/webhooks/{carrier_slug}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, Any],
)
@router.post(
    "/webhooks/{carrier_slug}",
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
)
async def receive_carrier_webhook(
    carrier_slug: str,
    request: Request,
    content_type: str = Header(default="application/json"),
    db: AsyncSession = Depends(get_db),
    rmq: RabbitMQService = Depends(get_rabbitmq_service),
) -> dict[str, Any]:
    """Receive push tracking events from Type A carrier webhooks (F3 / RNF-01).

    Decodes heterogeneous payloads and publishes to RabbitMQ queue `eventos_transportadora`
    for asynchronous processing, guaranteeing response time < 200 ms (RNF-01).
    """
    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Empty webhook body",
        )

    # 1. Validar y decodificar el formato de la transportadora
    try:
        event = decode_carrier_payload(carrier_slug, content_type, body)
    except WebhookDecodeError as exc:
        logger.warning("Failed to decode webhook for %s: %s", carrier_slug, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid webhook payload: {exc}",
        ) from exc

    # 2. Validar que la transportadora exista en el sistema (404 si no existe)
    carrier = await find_carrier_by_slug_or_id(db, carrier_slug)
    if carrier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Carrier '{carrier_slug}' is not registered in the system",
        )

    # 3. Publicar en la cola RabbitMQ de forma asíncrona (RNF-01)
    try:
        queued_msg: QueuedWebhookMessage = await rmq.publish_webhook_event(
            carrier_slug=carrier.name,
            event=event,
            content_type=content_type,
        )
    except Exception as exc:
        logger.error("Failed to publish webhook to RabbitMQ for %s: %s", carrier_slug, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Messaging queue broker unavailable",
        ) from exc

    return {
        "status": "queued",
        "message_id": queued_msg.message_id,
        "carrier": carrier.name,
        "carrier_id": carrier.carrier_id,
        "tracking_number": event.tracking_number,
        "raw_status": event.raw_status,
        "enqueued_at": queued_msg.enqueued_at,
        "message": "Event published to RabbitMQ queue 'eventos_transportadora' for async processing.",
    }
