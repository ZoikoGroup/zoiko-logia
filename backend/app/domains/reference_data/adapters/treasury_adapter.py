"""
U.S. Treasury Fiscal Data adapter — read-only wrapper around the public
Rates of Exchange dataset. This source requires no API key (public,
no-auth endpoint) — do not add key/env var handling for it. The base URL
itself is configured, not hardcoded — see TREASURY_FISCAL_DATA_BASE_URL in
app/core/config.py (backend/.env) — so it's one setting, not a string
repeated across files.

Nothing outside app/domains/reference_data/ should import this module
directly. Kriton's retrieval layer (and everything else) goes through
service.py instead, which is what gives every external call the audit
trail and caching the reference-data doctrine requires.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings

_RATES_OF_EXCHANGE_PATH = "/accounting/od/rates_of_exchange"
_REQUEST_TIMEOUT_SECONDS = 10.0


class TreasuryAPIError(Exception):
    """Raised for any non-200 response or transport failure — callers never
    see a raw httpx exception."""


async def get_exchange_rates(currency: str | None = None, since: str = "2020-01-01") -> list[dict]:
    filters = [f"record_date:gte:{since}"]
    if currency:
        filters.append(f"country_currency_desc:in:({currency})")

    params = {
        "fields": "country_currency_desc,exchange_rate,record_date",
        "filter": ",".join(filters),
        "sort": "-record_date",
    }

    base_url = get_settings().TREASURY_FISCAL_DATA_BASE_URL

    try:
        async with httpx.AsyncClient(
            base_url=base_url, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(_RATES_OF_EXCHANGE_PATH, params=params)
    except httpx.TimeoutException as exc:
        raise TreasuryAPIError(
            f"Treasury Fiscal Data API timed out after {_REQUEST_TIMEOUT_SECONDS}s"
        ) from exc
    except httpx.HTTPError as exc:
        raise TreasuryAPIError(f"Treasury Fiscal Data API request failed: {exc}") from exc

    if response.status_code != 200:
        raise TreasuryAPIError(
            f"Treasury Fiscal Data API returned {response.status_code}: {response.text[:200]}"
        )

    try:
        return response.json()["data"]
    except (ValueError, KeyError) as exc:
        raise TreasuryAPIError(f"Unexpected Treasury Fiscal Data API response shape: {exc}") from exc
