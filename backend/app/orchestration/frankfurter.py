"""
Frankfurter exchange-rate retrieval for Ask Kriton™.

Frankfurter (https://frankfurter.dev) is a free, keyless API serving the ECB's
daily reference exchange rates. When a question is about currency conversion or
an exchange rate, this fetches the live rate and returns it as a WebSource — the
SAME shape SearXNG results use — so it merges straight into the existing grounded
answer pipeline (grounding context + [REF-N] source panel) with no other change.

Fails soft: returns [] on any non-FX question, missing currencies, or network/
parse error, so the bot simply falls back to its normal web-grounded answer.
"""
from __future__ import annotations

import os
import re
import uuid

import httpx

from app.orchestration.websearch import WebSource
from app.domains.calculations.schemas import LiveObservation

# Common ISO-4217 currency codes we recognise in a question. Advisory only —
# Frankfurter itself validates; anything it rejects just yields no rate.
_CURRENCY_CODES = {
    "USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "CHF", "CNY", "HKD",
    "SGD", "NZD", "SEK", "NOK", "DKK", "ZAR", "AED", "SAR", "BRL", "MXN",
    "RUB", "KRW", "TRY", "PLN", "THB", "IDR", "MYR", "PHP", "CZK", "HUF",
    "ILS", "RON", "BGN", "ISK",
}

# Signals that the question is actually about currency/FX (so we don't fire on a
# random 3-letter token that happens to look like a code).
_FX_HINTS = re.compile(r"\b(convert|conversion|exchange rate|forex|fx|currency|rate of|in terms of|worth in|equal to)\b", re.I)


def _frankfurter_base() -> str:
    return os.getenv("FRANKFURTER_API_BASE_URL", "https://api.frankfurter.dev/v1").rstrip("/")


def _find_currencies(query: str) -> list[str]:
    # Match standalone 3-letter tokens, uppercased, that are known codes —
    # preserve order, drop duplicates.
    seen: list[str] = []
    for tok in re.findall(r"\b[A-Za-z]{3}\b", query):
        code = tok.upper()
        if code in _CURRENCY_CODES and code not in seen:
            seen.append(code)
    return seen


def _find_amount(query: str) -> float:
    m = re.search(r"\b(\d+(?:[.,]\d+)?)\b", query.replace(",", ""))
    return float(m.group(1)) if m else 1.0


async def fetch_fx(query: str) -> list[WebSource]:
    """Return one WebSource per base/target currency pair — the first
    recognised code is the base, every other recognised code is a target
    rate against it — when the question names two or more currencies;
    otherwise [].

    A query naming three-plus codes ("compare USD to EUR and USD to GBP")
    previously only ever looked at codes[0]/codes[1] and silently dropped
    every other pair, e.g. losing GBP from that exact question. Frankfurter's
    /latest endpoint accepts a comma-separated symbols list, so every target
    is still fetched in a single request, not one per pair."""
    codes = _find_currencies(query)
    # Need two currencies (from -> to). Require either two codes, or one code
    # plus an explicit FX hint (still need a second to convert, so two codes).
    if len(codes) < 2:
        return []
    if not (_FX_HINTS.search(query) or len(codes) >= 2):
        return []

    base_cur, quote_curs = codes[0], codes[1:]
    amount = _find_amount(query)
    base = _frankfurter_base()
    url = f"{base}/latest?base={base_cur}&symbols={','.join(quote_curs)}"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        rates = data.get("rates") or {}
        date = data.get("date", "")
    except Exception:
        return []

    sources: list[WebSource] = []
    for quote_cur in quote_curs:
        raw_rate = rates.get(quote_cur)
        if raw_rate is None:
            continue
        rate = float(raw_rate)
        converted = amount * rate
        snippet = (
            f"Live ECB reference rate (Frankfurter), {date}: "
            f"1 {base_cur} = {rate:g} {quote_cur}. "
            f"{amount:g} {base_cur} = {converted:g} {quote_cur}."
        )
        pair_url = f"{base}/latest?base={base_cur}&symbols={quote_cur}"
        sources.append(
            WebSource(
                title=f"Frankfurter — {base_cur}/{quote_cur} exchange rate ({date})",
                url=pair_url,
                snippet=snippet,
                provider="Frankfurter (ECB reference rates)",
                freshness="daily",
                observation=LiveObservation(
                    observation_id=f"obs_{uuid.uuid4().hex}",
                    indicator=f"{base_cur}/{quote_cur} exchange rate",
                    value=str(rate), unit=f"{quote_cur} per {base_cur}", period=str(date),
                    provider="Frankfurter (ECB reference rates)", source_url=pair_url,
                    freshness="daily",
                ),
            )
        )
    return sources
