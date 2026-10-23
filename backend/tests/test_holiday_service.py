from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.schemas.sla import PublicHoliday
from app.services.holiday_service import HolidayService


@pytest.fixture
def fresh_holiday_service() -> HolidayService:
    """Provide an isolated holiday service instance with an empty cache."""
    service = HolidayService(base_url="https://date.nager.at/api/v3", cache_ttl_seconds=3600)
    service.clear_cache()
    return service


@pytest.mark.asyncio
async def test_preload_holidays_and_is_holiday(fresh_holiday_service: HolidayService) -> None:
    service = fresh_holiday_service
    # Preload string and date objects
    service.preload_holidays("CO", 2026, ["2026-01-01", date(2026, 5, 1), "2026-10-26"])

    assert await service.is_holiday("CO", date(2026, 1, 1)) is True
    assert await service.is_holiday("CO", date(2026, 5, 1)) is True
    assert await service.is_holiday("CO", date(2026, 10, 26)) is True
    assert await service.is_holiday("CO", date(2026, 10, 27)) is False
    assert await service.is_holiday("MX", date(2026, 10, 27)) is False


@pytest.mark.asyncio
async def test_fetch_from_api_success(fresh_holiday_service: HolidayService) -> None:
    service = fresh_holiday_service

    mock_payload = [
        {
            "date": "2026-01-01",
            "localName": "Año Nuevo",
            "name": "New Year's Day",
            "countryCode": "CO",
            "fixed": True,
            "global": True,
        },
        {
            "date": "2026-10-26",
            "localName": "Día de la Raza",
            "name": "Columbus Day",
            "countryCode": "CO",
            "fixed": False,
            "global": True,
        },
    ]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        holidays = await service.get_holidays("CO", 2026)

        assert mock_get.await_count == 1
        assert date(2026, 1, 1) in holidays
        assert date(2026, 10, 26) in holidays
        assert len(holidays) == 2

        # Second call must use cache and NOT hit HTTP client
        cached_holidays = await service.get_holidays("CO", 2026)
        assert mock_get.await_count == 1  # Still 1, verified cache hit!
        assert cached_holidays == holidays


@pytest.mark.asyncio
async def test_get_holiday_details(fresh_holiday_service: HolidayService) -> None:
    service = fresh_holiday_service

    mock_payload = [
        {
            "date": "2026-10-26",
            "localName": "Festivo",
            "name": "Holiday",
            "countryCode": "CO",
            "fixed": True,
            "global": True,
        }
    ]

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        details = await service.get_holiday_details("CO", 2026)
        assert len(details) == 1
        assert isinstance(details[0], PublicHoliday)
        assert details[0].date == date(2026, 10, 26)
        assert details[0].country_code == "CO"


@pytest.mark.asyncio
async def test_fetch_from_api_network_failure_gracefully_handled(
    fresh_holiday_service: HolidayService,
) -> None:
    service = fresh_holiday_service

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        # Must not raise exception, returns empty set
        holidays = await service.get_holidays("PE", 2026)
        assert holidays == set()
        assert await service.is_holiday("PE", date(2026, 7, 28)) is False


@pytest.mark.asyncio
async def test_fetch_from_api_fallback_to_stale_cache_on_error(
    fresh_holiday_service: HolidayService,
) -> None:
    service = fresh_holiday_service
    # Seed cache
    service.preload_holidays("MX", 2026, [date(2026, 9, 16)])

    # Force cache expiration
    service.cache_ttl_seconds = -1
    assert service.is_cache_valid("MX", 2026) is False

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Read timeout")

        # Network fails, but existing cache is retained
        holidays = await service.get_holidays("MX", 2026)
        assert date(2026, 9, 16) in holidays
