import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.exceptions import EntityNotFoundError
from app.services.normalization_service import normalize_and_apply_event
from app.services.webhook_decoders import WebhookDecodeError, decode_carrier_payload

logger = logging.getLogger("cargaexpress.webhooks")

router = APIRouter(tags=["webhooks"])


@router.post("/api/v1/webhooks/{carrier_slug}", status_code=status.HTTP_200_OK)
@router.post("/webhooks/{carrier_slug}", status_code=status.HTTP_200_OK, include_in_schema=False)
async def receive_carrier_webhook(
    carrier_slug: str,
    request: Request,
    content_type: str = Header(default="application/json"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Receive push tracking events from Type A carrier webhooks (F3 / RNF-01).

    Decodes heterogeneous payloads (flat JSON, nested JSON, Spanish JSON, XML, form-urlencoded)
    and passes the standardized event to NormalizationService to update canonical status.
    """
    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Empty webhook body",
        )

    # 1. Decodificar el formato propietario de la transportadora
    try:
        event = decode_carrier_payload(carrier_slug, content_type, body)
    except WebhookDecodeError as exc:
        logger.warning("Failed to decode webhook for %s: %s", carrier_slug, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid webhook payload: {exc}",
        ) from exc

    # 2. Conectar con el servicio de normalización
    try:
        result = await normalize_and_apply_event(
            db=db,
            carrier_identifier=carrier_slug,
            tracking_number=event.tracking_number,
            raw_status=event.raw_status,
            occurred_at=event.occurred_at,
            event_id=event.event_id,
            location=event.location,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Carrier '{carrier_slug}' is not registered in the system",
        ) from exc

    return {
        "status": "processed",
        "carrier_id": result.carrier_id,
        "tracking_number": result.tracking_number,
        "raw_status": result.raw_status,
        "canonical_status": result.canonical_status,
        "current_status": result.new_status,
        "is_anomaly": result.is_anomaly,
        "anomaly_reason": result.anomaly_reason,
        "message": result.message,
    }
