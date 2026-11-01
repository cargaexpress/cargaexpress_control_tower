import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.normalization_service import normalize_and_apply_event

logger = logging.getLogger("cargaexpress.type_a_connector")


@dataclass(slots=True)
class TypeACarrierSyncSummary:
    """Statistics for an ingestion cycle of Type A carrier simulator."""

    carrier: str
    total_fetched: int = 0
    normalized: int = 0
    anomalies: int = 0
    errors: int = 0
    status: str = "completed"
    error_message: str | None = None
    details: list[dict[str, Any]] = field(default_factory=list)


def _parse_event_time(event_time_str: str | None) -> datetime | None:
    if not event_time_str:
        return None
    try:
        dt = datetime.fromisoformat(event_time_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


class TypeAConnectorService:
    """HTTP client and pull-sync ingestion engine for Type A carrier simulator.

    Provides a polling bridge to the Webhook Simulator Receiver API
    (Source F3 / Receiver Extractor) for scheduled batch execution via Airflow.
    """

    def __init__(
        self,
        base_url: str | None = None,
        max_retries: int | None = None,
        base_delay_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
    ) -> None:
        self.base_url = (base_url or settings.type_a_simulator_url).rstrip("/")
        self.max_retries = max_retries if max_retries is not None else settings.type_a_max_retries
        self.base_delay = (
            base_delay_seconds
            if base_delay_seconds is not None
            else settings.type_a_retry_base_delay_seconds
        )
        self._external_client = client
        self._sleep = sleep_fn or asyncio.sleep

    async def check_simulator_health(self) -> dict[str, Any]:
        """Probe health endpoint of the Type A webhook simulator receiver."""
        url = f"{self.base_url}/health"
        async with (
            self._external_client if self._external_client else httpx.AsyncClient()
        ) as client:
            try:
                resp = await client.get(url, timeout=5.0)
                if resp.status_code == 200:
                    return resp.json()
                return {"status": "degraded", "http_status": resp.status_code}
            except Exception as exc:
                logger.warning("Type A simulator receiver unreachable: %s", exc)
                return {"status": "unreachable", "error": str(exc)}

    async def sync_carrier(
        self,
        db: AsyncSession,
        carrier_slug: str,
        limit: int = 50,
        after_id: int = 0,
    ) -> TypeACarrierSyncSummary:
        """Poll and ingest events for a specific Type A carrier from the simulator receiver."""
        summary = TypeACarrierSyncSummary(carrier=carrier_slug)
        url = f"{self.base_url}/events"
        params: dict[str, Any] = {"carrier": carrier_slug, "limit": limit, "after_id": after_id}

        async with (
            self._external_client if self._external_client else httpx.AsyncClient()
        ) as client:
            try:
                resp = await client.get(url, params=params, timeout=10.0)
                resp.raise_for_status()
                events = resp.json()
            except Exception as exc:
                logger.error("Failed to query Type A simulator for %s: %s", carrier_slug, exc)
                summary.status = "unreachable"
                summary.error_message = str(exc)
                return summary

            if not isinstance(events, list):
                summary.status = "invalid_response"
                summary.error_message = "Expected list of events from simulator"
                return summary

            summary.total_fetched = len(events)

            for raw_event in events:
                tracking_number = str(raw_event.get("tracking_number", "")).strip()
                raw_status = str(raw_event.get("raw_status", "")).strip()
                event_id = str(raw_event.get("event_id") or raw_event.get("id", ""))
                occurred_at = _parse_event_time(raw_event.get("occurred_at"))
                location = raw_event.get("location")

                if not tracking_number or not raw_status:
                    summary.errors += 1
                    continue

                try:
                    norm_result = await normalize_and_apply_event(
                        db=db,
                        carrier_identifier=carrier_slug,
                        tracking_number=tracking_number,
                        raw_status=raw_status,
                        event_id=event_id,
                        occurred_at=occurred_at,
                        location=location,
                    )
                    if norm_result.is_anomaly:
                        summary.anomalies += 1
                    summary.normalized += 1
                except Exception as norm_exc:
                    logger.warning(
                        "Normalization failure for %s (%s): %s",
                        carrier_slug,
                        tracking_number,
                        norm_exc,
                    )
                    summary.errors += 1

            return summary

    async def sync_all_carriers(
        self,
        db: AsyncSession,
        limit_per_carrier: int = 50,
    ) -> list[TypeACarrierSyncSummary]:
        """Poll and ingest events across all 5 Type A carriers (alpha, beta, gamma, delta, epsilon)."""
        carriers = ["alpha", "beta", "gamma", "delta", "epsilon"]
        summaries: list[TypeACarrierSyncSummary] = []

        for carrier in carriers:
            summary = await self.sync_carrier(
                db=db,
                carrier_slug=carrier,
                limit=limit_per_carrier,
            )
            summaries.append(summary)

        return summaries
