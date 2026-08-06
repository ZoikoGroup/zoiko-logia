"""
Bank of England Interactive Statistical Database (IADB) adapter — read-only
wrapper around its public CSV export, used for the UK policy interest rate
(Bank Rate — the direct UK equivalent of the US Fed funds rate). Public, no
API key required.

Unlike FRED's clean JSON API, IADB is a legacy CGI endpoint that returns raw
CSV for a given series code and date range — this module owns the CSV
parsing so every caller downstream still sees the same list-of-dicts shape
every other adapter in this package returns.

Nothing outside app/domains/reference_data/ should import this module
directly — see service.py for the audit-logged, cached entry point.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import httpx

from app.core.config import get_settings

_IADB_PATH = "/_iadb-fromshowcolumns.asp"
_REQUEST_TIMEOUT_SECONDS = 15.0

# IUDBEDR — Bank Rate (the UK policy rate set by the Monetary Policy
# Committee), the only series this integration exposes today. Confirmed
# live: returns a genuine daily rate history, not a placeholder/demo series.
BANK_RATE_SERIES_ID = "IUDBEDR"


class BankOfEnglandAPIError(Exception):
    """Safe wrapper for configuration, transport, and response failures."""


async def get_series_observations(series_id: str, *, lookback_days: int = 400) -> list[dict]:
    """Returns [{"date": "DD Mon YYYY", "value": "5.25"}, ...] oldest to
    newest, for the last lookback_days — plenty of headroom to compute a
    one-year change even accounting for the odd non-trading-day gap."""
    settings = get_settings()
    date_from = (date.today() - timedelta(days=lookback_days)).strftime("%d/%b/%Y")

    params = {
        "csv.x": "yes",
        "Datefrom": date_from,
        "Dateto": "now",
        "SeriesCodes": series_id,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    try:
        async with httpx.AsyncClient(
            base_url=settings.BANK_OF_ENGLAND_API_BASE_URL, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(_IADB_PATH, params=params, headers={"User-Agent": "Mozilla/5.0"})
    except httpx.TimeoutException as exc:
        raise BankOfEnglandAPIError(f"Bank of England API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise BankOfEnglandAPIError(f"Bank of England API request failed: {exc}") from exc

    if response.status_code != 200:
        raise BankOfEnglandAPIError(f"Bank of England API returned status {response.status_code}")

    reader = csv.DictReader(io.StringIO(response.text))
    rows = []
    for row in reader:
        raw_date = row.get("DATE")
        raw_value = row.get(series_id)
        if not raw_date or raw_value in (None, ""):
            continue
        rows.append({"date": raw_date, "value": raw_value})
    if not rows:
        raise BankOfEnglandAPIError(f"Bank of England API returned no observations for {series_id}")
    return rows
