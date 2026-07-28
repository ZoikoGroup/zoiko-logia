"""
US Bureau of Labor Statistics (BLS) Public Data API adapter — read-only
wrapper around the national Consumer Price Index for All Urban Consumers
(CPI-U, series CUUR0000SA0), used for headline US inflation questions.

Unlike Treasury/PayrollTax/Census (all GET requests), BLS's v2 API is a
POST with a JSON body — series IDs and the registration key both go in the
request payload, not the query string or a header.

Nothing outside app/domains/reference_data/ should import this module
directly — everything goes through service.py, which gives every external
call the audit trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_TIMESERIES_PATH = "/timeseries/data/"
_REQUEST_TIMEOUT_SECONDS = 10.0

# CPI-U, not seasonally adjusted, "All items" — the standard headline
# series used for year-over-year inflation reporting.
CPI_U_SERIES_ID = "CUUR0000SA0"


class BLSAPIError(Exception):
    """Raised for any non-200 response, API-level failure status, or
    transport failure — callers never see a raw httpx exception."""


async def get_cpi_series(start_year: str, end_year: str) -> list[dict]:
    settings = get_settings()
    payload = {
        "seriesid": [CPI_U_SERIES_ID],
        "startyear": start_year,
        "endyear": end_year,
    }
    if settings.BLS_API_KEY:
        payload["registrationkey"] = settings.BLS_API_KEY

    try:
        async with httpx.AsyncClient(
            base_url=settings.BLS_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(_TIMESERIES_PATH, json=payload)
    except httpx.TimeoutException as exc:
        raise BLSAPIError(f"BLS API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise BLSAPIError(f"BLS API request failed: {exc}") from exc

    if response.status_code != 200:
        raise BLSAPIError(f"BLS API returned {response.status_code}: {response.text[:200]}")

    try:
        body = response.json()
    except ValueError as exc:
        raise BLSAPIError(f"Unexpected BLS API response shape: {exc}") from exc

    if body.get("status") != "REQUEST_SUCCEEDED":
        raise BLSAPIError(f"BLS API request failed: {body.get('message') or body.get('status')}")

    series = body.get("Results", {}).get("series", [])
    if not series:
        raise BLSAPIError("BLS API returned no series data")

    return series[0].get("data", [])
