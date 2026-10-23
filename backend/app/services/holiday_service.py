import logging
import time
from collections.abc import Iterable
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.schemas.sla import PublicHoliday

logger = logging.getLogger(__name__)


class HolidayService:
    """Service to query, cache, and manage public holidays via Nager.Date API (source F6)."""

    def __init__(self, base_url: str | None = None, cache_ttl_seconds: int | None = None) -> None:
        self.base_url = (base_url or settings.nager_date_api_url).rstrip("/")
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings.holiday_cache_ttl_seconds
        )
        self._cache: dict[tuple[str, int], set[date]] = {}
        self._details_cache: dict[tuple[str, int], list[PublicHoliday]] = {}
        self._cache_timestamps: dict[tuple[str, int], float] = {}

    def clear_cache(self) -> None:
        """Clear all cached holidays."""
        self._cache.clear()
        self._details_cache.clear()
        self._cache_timestamps.clear()

    def preload_holidays(
        self,
        country_code: str,
        year: int,
        holidays: Iterable[date | str],
    ) -> None:
        """Preload holiday dates into cache for testing or offline environments."""
        normalized_country = country_code.strip().upper()
        date_set: set[date] = set()
        for item in holidays:
            if isinstance(item, str):
                date_set.add(date.fromisoformat(item))
            elif isinstance(item, date):
                date_set.add(item)

        key = (normalized_country, year)
        self._cache[key] = date_set
        self._cache_timestamps[key] = time.monotonic()
        logger.debug(
            "Preloaded %d holidays for %s/%d into cache",
            len(date_set),
            normalized_country,
            year,
        )

    def is_cache_valid(self, country_code: str, year: int) -> bool:
        """Check if cached holidays for country and year are present and unexpired."""
        key = (country_code, year)
        if key not in self._cache:
            return False
        elapsed = time.monotonic() - self._cache_timestamps.get(key, 0.0)
        return elapsed < self.cache_ttl_seconds

    async def fetch_from_api(
        self,
        country_code: str,
        year: int,
    ) -> list[PublicHoliday]:
        """Fetch holidays from external Nager.Date API."""
        url = f"{self.base_url}/PublicHolidays/{year}/{country_code}"
        logger.info("Fetching public holidays from Nager.Date: %s", url)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data: list[dict[str, Any]] = response.json()

        holidays: list[PublicHoliday] = []
        for item in data:
            try:
                holiday_date = (
                    date.fromisoformat(item["date"])
                    if isinstance(item["date"], str)
                    else item["date"]
                )
                holidays.append(
                    PublicHoliday(
                        date=holiday_date,
                        local_name=item.get("localName", "Holiday"),
                        name=item.get("name", "Holiday"),
                        country_code=item.get("countryCode", country_code),
                        fixed=item.get("fixed", True),
                        global_holiday=item.get("global", True),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping invalid holiday item %s: %s", item, exc)

        return holidays

    async def get_holidays(self, country_code: str, year: int) -> set[date]:
        """Get set of holiday dates for a given country and year, using cache or fetching from API."""
        normalized_country = country_code.strip().upper()
        key = (normalized_country, year)

        if self.is_cache_valid(normalized_country, year):
            return self._cache[key]

        try:
            holiday_objects = await self.fetch_from_api(normalized_country, year)
            date_set = {h.date for h in holiday_objects}
            self._cache[key] = date_set
            self._details_cache[key] = holiday_objects
            self._cache_timestamps[key] = time.monotonic()
            logger.info(
                "Cached %d holidays for country %s and year %d",
                len(date_set),
                normalized_country,
                year,
            )
            return date_set
        except Exception as exc:
            logger.warning(
                "Failed to fetch holidays from Nager.Date for %s/%d (%s). Falling back to existing cache if available.",
                normalized_country,
                year,
                exc,
            )
            if key in self._cache:
                return self._cache[key]
            return set()

    async def get_holiday_details(self, country_code: str, year: int) -> list[PublicHoliday]:
        """Get full public holiday details for a country and year."""
        normalized_country = country_code.strip().upper()
        key = (normalized_country, year)
        if not self.is_cache_valid(normalized_country, year):
            await self.get_holidays(normalized_country, year)
        return self._details_cache.get(key, [])

    async def is_holiday(self, country_code: str, target_date: date) -> bool:
        """Check if a specific calendar date is a public holiday in the given country."""
        holidays = await self.get_holidays(country_code, target_date.year)
        return target_date in holidays


holiday_service = HolidayService()
