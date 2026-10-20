import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.type_b_connector import TypeBConnectorService

logger = logging.getLogger("cargaexpress.type_b_router")

router = APIRouter(prefix="/api/v1/sync", tags=["connectors: type b"])


@router.post("/type-b")
async def trigger_type_b_sync(
    carrier_name: str | None = Query(
        default=None,
        description="Optional carrier name to sync. If omitted, syncs all 4 Type B carriers.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger periodic polling connector for Type B carriers (F4 / Airflow batch hook).

    Queries carrier REST APIs, respects rate limits with exponential backoff,
    and passes all tracking events through NormalizationService (RN-01 / RN-02).
    """
    service = TypeBConnectorService()

    if carrier_name:
        from app.config import settings

        base_url = settings.type_b_carriers_urls.get(carrier_name, "http://localhost:8001")
        summary = await service.sync_carrier(db, carrier_name, base_url)
        return {
            "status": "completed",
            "results": [
                {
                    "carrier": summary.carrier,
                    "total_fetched": summary.total_fetched,
                    "normalized": summary.normalized,
                    "anomalies": summary.anomalies,
                    "errors": summary.errors,
                    "rate_limits_encountered": summary.rate_limits_encountered,
                    "sync_status": summary.status,
                    "error_message": summary.error_message,
                }
            ],
        }

    summaries = await service.sync_all_carriers(db)
    return {
        "status": "completed",
        "results": [
            {
                "carrier": s.carrier,
                "total_fetched": s.total_fetched,
                "normalized": s.normalized,
                "anomalies": s.anomalies,
                "errors": s.errors,
                "rate_limits_encountered": s.rate_limits_encountered,
                "sync_status": s.status,
                "error_message": s.error_message,
            }
            for s in summaries
        ],
    }
