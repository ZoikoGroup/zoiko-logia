"""
US Census Bureau American Community Survey (ACS) adapter — read-only
wrapper around the 1-year ACS estimates for state-level median household
income and poverty statistics. Keyed via a query-string `key=` param
(unlike Treasury/PayrollTax's header-based auth).

Nothing outside app/domains/reference_data/ should import this module
directly — everything goes through service.py, which gives every external
call the audit trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_ACS1_DATASET = "acs/acs1"
_REQUEST_TIMEOUT_SECONDS = 10.0

# American Community Survey table variables — stable, well-documented
# Census Bureau codes, not something that changes year to year.
#   B19013_001E = median household income (past 12 months, inflation-adj $)
#   B17001_001E = population for whom poverty status is determined
#   B17001_002E = population below the poverty level
_VARIABLES = "NAME,B19013_001E,B17001_001E,B17001_002E"


class CensusAPIError(Exception):
    """Raised for any non-200 response or transport failure — callers never
    see a raw httpx exception."""


async def get_state_income_poverty(state_fips: str, year: str) -> dict:
    settings = get_settings()
    params = {
        "get": _VARIABLES,
        "for": f"state:{state_fips}",
        "key": settings.CENSUS_API_KEY,
    }

    try:
        async with httpx.AsyncClient(
            base_url=settings.CENSUS_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(f"/{year}/{_ACS1_DATASET}", params=params)
    except httpx.TimeoutException as exc:
        raise CensusAPIError(f"Census API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise CensusAPIError(f"Census API request failed: {exc}") from exc

    if response.status_code != 200:
        raise CensusAPIError(f"Census API returned {response.status_code}: {response.text[:200]}")

    try:
        rows = response.json()
    except ValueError as exc:
        raise CensusAPIError(f"Unexpected Census API response shape: {exc}") from exc

    # Census's API returns a list-of-lists with the header row first, not a
    # list of objects like Treasury/PayrollTax — [header, data_row].
    if not isinstance(rows, list) or len(rows) < 2:
        raise CensusAPIError(f"Unexpected Census API response shape: {rows!r}"[:200])

    header, data_row = rows[0], rows[1]
    return dict(zip(header, data_row))
