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
from dataclasses import dataclass

import httpx

from app.orchestration.websearch import WebSource

# Currencies Frankfurter (ECB daily reference rates) actually publishes —
# NOT a generic ISO-4217 list. AED, SAR and RUB were previously included here
# despite Frankfurter never having rates for them: _find_rate would silently
# return None for those pairs, and the LLM would then fill the gap with an
# approximate rate from its own training data instead of an honest "not
# available" — a real fabrication bug found via live testing. Keep this list
# exactly matched to https://frankfurter.dev's supported currencies so a
# "recognised" code always means Frankfurter can actually answer for it.
_CURRENCY_CODES = {
    "USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "CHF", "CNY", "HKD",
    "SGD", "NZD", "SEK", "NOK", "DKK", "ZAR", "BRL", "MXN",
    "KRW", "TRY", "PLN", "THB", "IDR", "MYR", "PHP", "CZK", "HUF",
    "ILS", "RON", "BGN", "ISK",
}


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
    # Strip thousands separators before parsing, but do not remove every
    # comma from the query (which could join unrelated tokens).
    normalized = re.sub(r"(?<=\d),(?=\d{3}\b)", "", query)
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", normalized)
    return float(m.group(1)) if m else 1.0


@dataclass
class RateMatch:
    """The full result of a Frankfurter lookup — WebSource text (via fetch_fx)
    and structured evidence are both built from this SAME object, so they can
    never disagree about the underlying rate."""

    base_cur: str
    quote_cur: str
    rate: float
    amount: float
    converted: float
    date: str
    url: str


async def _find_rate(query: str) -> RateMatch | None:
    """One HTTP round-trip to Frankfurter, returning the matched rate (or
    None). The sole source of truth both fetch_fx() and the structured
    evidence path build from."""
    codes = _find_currencies(query)
    # Two recognised currency codes (from -> to) is itself a strong enough
    # signal — no separate FX-hint check needed on top of it (a prior version
    # of this check was a tautology: it only ever ran once len(codes) >= 2
    # was already known true, so it could never actually reject anything).
    if len(codes) < 2:
        return None

    base_cur, quote_cur = codes[0], codes[1]
    amount = _find_amount(query)
    base = _frankfurter_base()
    url = f"{base}/latest?base={base_cur}&symbols={quote_cur}"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        rate = float((data.get("rates") or {}).get(quote_cur))
        date = data.get("date", "")
    except Exception:
        return None

    return RateMatch(
        base_cur=base_cur, quote_cur=quote_cur, rate=rate,
        amount=amount, converted=amount * rate, date=date, url=url,
    )


def _build_source(match: RateMatch) -> WebSource:
    snippet = (
        f"Live ECB reference rate (Frankfurter), {match.date}: "
        f"1 {match.base_cur} = {match.rate:g} {match.quote_cur}. "
        f"{match.amount:g} {match.base_cur} = {match.converted:g} {match.quote_cur}."
    )
    return WebSource(
        title=f"Frankfurter — {match.base_cur}/{match.quote_cur} exchange rate ({match.date})",
        url=match.url,
        snippet=snippet,
    )


async def fetch_fx(query: str) -> list[WebSource]:
    """Return a single WebSource with the live exchange rate when the question
    is an FX/currency query with two recognised currencies; otherwise []."""
    match = await _find_rate(query)
    return [_build_source(match)] if match else []
