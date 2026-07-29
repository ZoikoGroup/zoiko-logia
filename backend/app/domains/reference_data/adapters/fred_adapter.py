"""
Federal Reserve Economic Data (FRED, St. Louis Fed) API adapter — read-only
wrapper around /fred/series/observations, used for headline US interest
rate questions (Fed funds rate, Treasury yields, prime rate, mortgage
rates). Keyed via a query-string `api_key=` param, like Census/BEA.

FRED only returns one series per request — service.py fetches several
series concurrently to build one combined interest-rates bundle.

Nothing outside app/domains/reference_data/ should import this module
directly — everything goes through service.py, which gives every external
call the audit trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_OBSERVATIONS_PATH = "/series/observations"
_REQUEST_TIMEOUT_SECONDS = 10.0


class FREDAPIError(Exception):
    """Raised for any non-200 response, API-level error, or transport
    failure — callers never see a raw httpx exception."""


async def get_series_observations(
    series_id: str,
    *,
    limit: int = 6,
    observation_start: str | None = None,
) -> list[dict]:
    settings = get_settings()
    params = {
        "series_id": series_id,
        "api_key": settings.FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    if observation_start:
        params["observation_start"] = observation_start

    try:
        async with httpx.AsyncClient(
            base_url=settings.FRED_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(_OBSERVATIONS_PATH, params=params)
    except httpx.TimeoutException as exc:
        raise FREDAPIError(f"FRED API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise FREDAPIError(f"FRED API request failed: {exc}") from exc

    if response.status_code != 200:
        raise FREDAPIError(f"FRED API returned {response.status_code}: {response.text[:200]}")

    try:
        body = response.json()
    except ValueError as exc:
        raise FREDAPIError(f"Unexpected FRED API response shape: {exc}") from exc

    if "error_message" in body:
        raise FREDAPIError(f"FRED API request failed: {body['error_message']}")

    observations = body.get("observations")
    if not observations:
        raise FREDAPIError(f"FRED API returned no observations for series {series_id}")

    return observations
