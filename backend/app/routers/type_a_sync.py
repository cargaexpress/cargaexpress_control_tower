import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.type_a_connector import TypeAConnectorService

logger = logging.getLogger("cargaexpress.type_a_router")

router = APIRouter(prefix="/api/v1/sync", tags=["connectors: type a"])


@router.post("/type-a")
async def trigger_type_a_sync(
    carrier_slug: str | None = Query(
        default=None,
        description="Optional carrier slug (alpha, beta, gamma, delta, epsilon). If omitted, syncs all 5 carriers.",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max events to pull per carrier."),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger periodic polling connector for Type A simulator receiver (F3 Airflow batch hook).

    Queries simulator receiver REST APIs, normalizes tracking statuses into canonical states,
    and updates WMS database with RN-01 and RN-02 compliance.
    """
    service = TypeAConnectorService()

    if carrier_slug:
        summary = await service.sync_carrier(db, carrier_slug=carrier_slug, limit=limit)
        return {
            "status": "completed",
            "results": [
                {
                    "carrier": summary.carrier,
                    "total_fetched": summary.total_fetched,
                    "normalized": summary.normalized,
                    "anomalies": summary.anomalies,
                    "errors": summary.errors,
                    "sync_status": summary.status,
                    "error_message": summary.error_message,
                }
            ],
        }

    summaries = await service.sync_all_carriers(db, limit_per_carrier=limit)
    return {
        "status": "completed",
        "results": [
            {
                "carrier": s.carrier,
                "total_fetched": s.total_fetched,
                "normalized": s.normalized,
                "anomalies": s.anomalies,
                "errors": s.errors,
                "sync_status": s.status,
                "error_message": s.error_message,
            }
            for s in summaries
        ],
    }
