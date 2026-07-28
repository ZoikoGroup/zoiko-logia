"""
US Bureau of Economic Analysis (BEA) API adapter — read-only wrapper around
the NIPA "GDP and its major components" table (T10105), used for headline
US GDP questions. Keyed via a query-string `UserID=` param (GET, like
Census), not a header.

Nothing outside app/domains/reference_data/ should import this module
directly — everything goes through service.py, which gives every external
call the audit trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_REQUEST_TIMEOUT_SECONDS = 15.0

# NIPA Table 1.1.5 — "Gross Domestic Product" — the standard headline
# quarterly report: GDP plus its major components (personal consumption,
# private investment, net exports, government spending), all in current
# dollars. One table covers the "core NIPA aggregates" scope without
# requiring a second dataset/table call.
GDP_TABLE_NAME = "T10105"
REAL_GDP_CHANGE_TABLE_NAME = "T10101"


class BEAAPIError(Exception):
    """Raised for any non-200 response, API-level error, or transport
    failure — callers never see a raw httpx exception."""


async def get_gdp_data(
    years: str,
    *,
    table_name: str = GDP_TABLE_NAME,
    frequency: str = "Q",
) -> list[dict]:
    """years: a BEA `Year` param value, e.g. "2025,2026" or "X" for the most
    recent single year — comma-separated literals only, no natural-language
    parsing."""
    settings = get_settings()
    params = {
        "UserID": settings.BEA_API_KEY,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": table_name,
        "Frequency": frequency,
        "Year": years,
        "ResultFormat": "JSON",
    }

    try:
        async with httpx.AsyncClient(
            base_url=settings.BEA_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.get("/", params=params)
    except httpx.TimeoutException as exc:
        raise BEAAPIError(f"BEA API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise BEAAPIError(f"BEA API request failed: {exc}") from exc

    if response.status_code != 200:
        raise BEAAPIError(f"BEA API returned {response.status_code}: {response.text[:200]}")

    try:
        body = response.json()
    except ValueError as exc:
        raise BEAAPIError(f"Unexpected BEA API response shape: {exc}") from exc

    results = body.get("BEAAPI", {}).get("Results", {})
    error = results.get("Error")
    if error:
        raise BEAAPIError(f"BEA API request failed: {error.get('APIErrorDescription') or error}")

    data = results.get("Data")
    if not data:
        raise BEAAPIError("BEA API returned no data rows")

    return data
