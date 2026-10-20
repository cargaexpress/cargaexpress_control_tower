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

logger = logging.getLogger("cargaexpress.type_b_connector")


class TypeBConnectorError(Exception):
    """Base exception for Type B connector errors."""


class TypeBRateLimitError(TypeBConnectorError):
    """Raised when rate limits are exhausted after retries."""


@dataclass(slots=True)
class CarrierSyncSummary:
    """Statistics for an ingestion cycle of a Type B carrier."""

    carrier: str
    total_fetched: int = 0
    normalized: int = 0
    anomalies: int = 0
    errors: int = 0
    rate_limits_encountered: int = 0
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


class TypeBConnectorService:
    """HTTP client and ingestion engine for Type B carriers (F4 / Periodic pull).

    Subtasks:
    1. HTTP Client: Queries carrier REST API endpoints (`/events`) with pagination.
    2. Reuse Normalization: Applies `normalize_and_apply_event` for canonical state and RN-02.
    3. Rate Limits & Retries: Exponential backoff on HTTP 429 and 5xx errors.
    """

    def __init__(
        self,
        max_retries: int | None = None,
        base_delay_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
    ) -> None:
        self.max_retries = max_retries if max_retries is not None else settings.type_b_max_retries
        self.base_delay = (
            base_delay_seconds
            if base_delay_seconds is not None
            else settings.type_b_retry_base_delay_seconds
        )
        self._external_client = client
        self._sleep = sleep_fn or asyncio.sleep

    async def fetch_events_page_with_retries(
        self,
        client: httpx.AsyncClient,
        url: str,
        limit: int,
        offset: int,
        summary: CarrierSyncSummary,
    ) -> dict[str, Any]:
        """Fetch a single page of events, applying exponential backoff on 429 / 5xx."""
        params = {"limit": limit, "offset": offset}

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(url, params=params, timeout=10.0)

                # HTTP 429 Too Many Requests -> Subtarea 3: Rate limit handling
                if response.status_code == 429:
                    summary.rate_limits_encountered += 1
                    if attempt == self.max_retries:
                        raise TypeBRateLimitError(
                            f"Rate limit exceeded on {url} after {self.max_retries} retries"
                        )

                    retry_after = response.headers.get("Retry-After")
                    delay = (
                        float(retry_after)
                        if retry_after and retry_after.isdigit()
                        else self.base_delay * (2**attempt)
                    )
                    logger.warning(
                        "Rate limit (429) hit on %s. Backing off for %.2fs (attempt %d/%d)",
                        url,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await self._sleep(delay)
                    continue

                # HTTP 5xx Server Error -> Transient error retry
                if response.status_code >= 500:
                    if attempt == self.max_retries:
                        response.raise_for_status()

                    delay = self.base_delay * (2**attempt)
                    logger.warning(
                        "Server error (%d) on %s. Retrying in %.2fs (attempt %d/%d)",
                        response.status_code,
                        url,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await self._sleep(delay)
                    continue

                response.raise_for_status()
                return response.json()

            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == self.max_retries:
                    raise TypeBConnectorError(f"Failed to fetch events from {url}: {exc}") from exc

                delay = self.base_delay * (2**attempt)
                logger.warning(
                    "Network error on %s: %s. Retrying in %.2fs (attempt %d/%d)",
                    url,
                    exc,
                    delay,
                    attempt + 1,
                    self.max_retries,
                )
                await self._sleep(delay)

        raise TypeBConnectorError(f"Exhausted retries querying {url}")

    async def sync_carrier(
        self,
        db: AsyncSession,
        carrier_name: str,
        base_url: str,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> CarrierSyncSummary:
        """Poll and ingest all pending events for one Type B carrier."""
        summary = CarrierSyncSummary(carrier=carrier_name)
        url = f"{base_url.rstrip('/')}/events"

        async with (
            self._external_client if self._external_client else httpx.AsyncClient()
        ) as client:
            offset = 0

            for _ in range(max_pages):
                try:
                    payload = await self.fetch_events_page_with_retries(
                        client=client,
                        url=url,
                        limit=page_size,
                        offset=offset,
                        summary=summary,
                    )
                except Exception as exc:
                    logger.error("Error syncing carrier %s: %s", carrier_name, exc)
                    summary.status = "failed"
                    summary.error_message = str(exc)
                    return summary

                events = payload.get("events", [])
                if not events:
                    break

                summary.total_fetched += len(events)

                # Subtarea 2: Reutilizar el servicio de normalización
                for raw_event in events:
                    tracking_number = str(raw_event.get("tracking_number", "")).strip()
                    raw_status = str(raw_event.get("status", "")).strip()
                    event_id = str(raw_event.get("event_key") or raw_event.get("event_id", ""))
                    occurred_at = _parse_event_time(raw_event.get("event_time"))

                    if not tracking_number or not raw_status:
                        summary.errors += 1
                        continue

                    try:
                        norm_result = await normalize_and_apply_event(
                            db=db,
                            carrier_identifier=carrier_name,
                            tracking_number=tracking_number,
                            raw_status=raw_status,
                            occurred_at=occurred_at,
                            event_id=event_id,
                        )
                        if norm_result.is_anomaly:
                            summary.anomalies += 1
                        else:
                            summary.normalized += 1

                    except Exception as exc:
                        logger.warning(
                            "Failed to normalize event for tracking %s: %s", tracking_number, exc
                        )
                        summary.errors += 1

                total = payload.get("total", 0)
                offset += len(events)
                if offset >= total or len(events) < page_size:
                    break

        return summary

    async def sync_all_carriers(
        self,
        db: AsyncSession,
        carriers_map: dict[str, str] | None = None,
        page_size: int = 100,
    ) -> list[CarrierSyncSummary]:
        """Poll and ingest events from all configured Type B carriers."""
        targets = carriers_map or settings.type_b_carriers_urls
        results: list[CarrierSyncSummary] = []

        for carrier_name, base_url in targets.items():
            res = await self.sync_carrier(
                db=db,
                carrier_name=carrier_name,
                base_url=base_url,
                page_size=page_size,
            )
            results.append(res)

        return results
