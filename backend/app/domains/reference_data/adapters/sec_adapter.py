"""
SEC EDGAR (data.sec.gov) adapter — read-only wrapper around the public
company-facts XBRL API. Free, no API key required, but the SEC requires a
descriptive User-Agent identifying the caller on every request (their
published fair-access policy) — see SEC_USER_AGENT in app/core/config.py.

Identifier-driven, same posture as congress_adapter.py: only a real ticker
symbol resolves to a company, and only a known financial-concept alias
resolves to a value — this is never a free-text company/financial search.

Nothing outside app/domains/reference_data/ should import this module
directly — see service.py for the audit-logged, cached entry point.
"""
from __future__ import annotations

import time

import httpx

from app.core.config import get_settings

# www.sec.gov, not data.sec.gov (SEC_DATA_API_BASE_URL) — the ticker lookup
# file is served from SEC's main site, a different host than the XBRL data
# API, so it's intentionally not driven by the configurable base URL below.
_TICKER_LOOKUP_URL = "https://www.sec.gov/files/company_tickers.json"
_REQUEST_TIMEOUT_SECONDS = 15.0

# Ticker -> CIK is a large (~10,000 row), slow-moving dataset — fetched once
# and cached in-process, same posture as reference_data/service.py's own
# _cache for exchange-rate bundles.
_TICKER_CACHE_TTL_SECONDS = 24 * 60 * 60
_ticker_cache: tuple[dict[str, dict], float] | None = None

# US-GAAP XBRL tag a company reports a concept under changes over time (e.g.
# ASC 606 adoption renamed revenue tags around 2018) and varies by company —
# real gap found live: Apple's "Revenues" tag has no data after 2018; the
# current tag is "RevenueFromContractWithCustomerExcludingAssessedTax". Each
# alias is tried in order; the first that returns real data wins, so this
# stays correct as tagging conventions evolve without needing a query-time
# guess about which exact tag a specific company currently uses.
_CONCEPT_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
}


class SECAPIError(Exception):
    """Safe wrapper for configuration, transport, and response failures."""


def _headers() -> dict:
    user_agent = get_settings().SEC_USER_AGENT
    if not user_agent:
        raise SECAPIError("SEC_USER_AGENT is not configured — required by SEC's fair-access policy")
    return {"User-Agent": user_agent}


async def _get_json(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=_headers())
    except httpx.TimeoutException as exc:
        raise SECAPIError(f"SEC API timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except httpx.HTTPError as exc:
        raise SECAPIError(f"SEC API request failed: {exc}") from exc

    if response.status_code == 404:
        raise SECAPIError("SEC did not find the requested company or concept")
    if response.status_code in {401, 403}:
        raise SECAPIError("SEC API rejected the request (missing/invalid User-Agent)")
    if response.status_code == 429:
        raise SECAPIError("SEC API rate limit exceeded")
    if response.status_code != 200:
        raise SECAPIError(f"SEC API returned status {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise SECAPIError("SEC API returned invalid JSON") from exc


async def _ticker_map() -> dict[str, dict]:
    global _ticker_cache
    now = time.monotonic()
    if _ticker_cache is not None and _ticker_cache[1] > now:
        return _ticker_cache[0]
    raw = await _get_json(_TICKER_LOOKUP_URL)
    by_ticker = {
        entry["ticker"].upper(): entry
        for entry in raw.values()
        if isinstance(entry, dict) and entry.get("ticker")
    }
    _ticker_cache = (by_ticker, now + _TICKER_CACHE_TTL_SECONDS)
    return by_ticker


async def resolve_cik(ticker: str) -> dict | None:
    """Returns {"cik_str": int, "ticker": str, "title": str} for a real
    ticker symbol, or None — never guesses a company from a partial name."""
    by_ticker = await _ticker_map()
    return by_ticker.get(ticker.upper())


async def get_company_concept(cik: int, concept: str) -> dict:
    """concept must be one of _CONCEPT_ALIASES' keys. Tries each known XBRL
    tag alias for that concept in order and returns the first with real
    annual (10-K) data — never invents or guesses a company's current tag."""
    aliases = _CONCEPT_ALIASES.get(concept)
    if not aliases:
        raise SECAPIError(f"Unknown concept: {concept}")

    padded_cik = f"{cik:010d}"
    base_url = get_settings().SEC_DATA_API_BASE_URL
    last_error: Exception | None = None
    for tag in aliases:
        url = f"{base_url}/api/xbrl/companyconcept/CIK{padded_cik}/us-gaap/{tag}.json"
        try:
            payload = await _get_json(url)
        except SECAPIError as exc:
            last_error = exc
            continue

        units = payload.get("units") or {}
        usd_values = units.get("USD") or []
        annual = [
            v for v in usd_values
            if isinstance(v, dict) and v.get("form") == "10-K" and v.get("fp") == "FY"
        ]
        if not annual:
            continue
        annual.sort(key=lambda v: v.get("end", ""))
        latest = annual[-1]
        return {
            "concept": concept,
            "tag": tag,
            "label": payload.get("label", tag),
            "value": latest.get("val"),
            "unit": "USD",
            "fiscal_year": latest.get("fy"),
            "period_start": latest.get("start"),
            "period_end": latest.get("end"),
            "filed": latest.get("filed"),
            "accession_number": latest.get("accn"),
        }
    raise last_error or SECAPIError(f"No annual 10-K data found for concept: {concept}")
