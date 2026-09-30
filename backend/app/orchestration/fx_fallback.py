"""Fallback FX rates for the currencies the ECB does not publish.

Frankfurter serves the European Central Bank's daily reference rates, covering
roughly 30 currencies. AED, SAR, NGN, EGP, PKR and the rest are simply absent,
and frankfurter.py's _UNSUPPORTED_ALIASES exists purely so Kriton can SAY that
instead of letting the model invent a rate. That honesty is right, but it is
not useful: those rates genuinely exist, they are just not ECB reference rates.

This module is the second link in that chain. Frankfurter stays primary because
an official central-bank reference rate outranks a market aggregator for
anything filed, taxed or audited — the whole product rests on the difference.
Only when Frankfurter has nothing to offer does this run, and whatever it
returns is labelled a market rate so no answer can present it as an official
reference. The distinction is the point, not a detail.

Self-gating is what makes it free on the common path: the query is inspected
with frankfurter.py's own currency table before any socket is opened, so a
question Frankfurter already answers costs one regex and no request. Matched at
most once, fetched at most once, fails soft like every other connector.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import httpx

from app.domains.calculations.schemas import LiveObservation
from app.orchestration.frankfurter import (
    RateMatch, _find_amount, _find_currency_mentions,
)
from app.orchestration.websearch import WebSource

PROVIDER = "open.er-api.com (market rate)"

# Same guard as fred.py's _fred_base(): a value pasted from a two-line example
# without its newline arrives as ".../v6/latest/USDOPEN_ER_API..." — plausible
# looking, and an invalid endpoint. Reject rather than request it.
_BASE_DEFAULT = "https://open.er-api.com/v6"


def _base() -> str:
    base = os.getenv("OPEN_ER_API_BASE_URL", _BASE_DEFAULT).strip().rstrip("/")
    if "=" in base or not base.startswith(("https://", "http://")):
        return _BASE_DEFAULT
    return base


def _is_gap_query(query: str) -> tuple[str, list[str]] | None:
    """(base, targets) when this query names a pair Frankfurter cannot serve.

    Returns None for anything Frankfurter can already answer, which is what
    keeps the fallback from ever competing with the official rate."""
    mentions = _find_currency_mentions(query)
    if len(mentions) < 2:
        return None
    if all(supported for _, supported in mentions):
        return None
    codes = [code for code, _ in mentions]
    return codes[0], codes[1:]


def _as_date(payload: dict) -> str:
    """The provider's "as of" date, preferring the machine-readable field.

    The unix stamp is preferred over the display string because it is
    unambiguous, and because the display string is RFC 1123 with a weekday
    prefix ("Wed, 04 Mar 2026 00:04:01 +0000") — matching that from the start
    of the string silently yields nothing and the raw header ends up in the
    citation. An unparseable date is still returned rather than dropped: the
    caller is better served by an imprecise date on an otherwise good source
    than by no source."""
    raw_unix = payload.get("time_last_update_unix")
    if isinstance(raw_unix, (int, float)) and raw_unix > 0:
        return datetime.fromtimestamp(raw_unix, timezone.utc).date().isoformat()
    utc = str(payload.get("time_last_update_utc") or "")
    stamp = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", utc)
    if stamp:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(
                    f"{stamp.group(1)} {stamp.group(2)} {stamp.group(3)}", fmt,
                ).date().isoformat()
            except ValueError:
                continue
    return utc


async def _find_fallback_rates(query: str) -> list[RateMatch]:
    """One HTTP round-trip for every pair Frankfurter could not serve.

    The first recognised currency is the base and the rest are targets against
    it, matching frankfurter.py's ordering so "1000 AED to NGN" and "1000 USD
    to NGN" behave the same way. open.er-api returns the full rate table for
    the requested base in one response, so any number of targets still costs
    exactly one request.
    """
    gap = _is_gap_query(query)
    if gap is None:
        return []
    base_cur, quote_curs = gap
    amount = _find_amount(query)
    base = _base()

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(f"{base}/latest/{base_cur}")
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    # A provider that reports its own failure as HTTP 200 with an error key is
    # a real behaviour of this API, so an empty/absent rate table is treated as
    # "nothing to say" rather than as data.
    if not isinstance(payload, dict) or str(payload.get("result", "success")).lower() == "error":
        return []
    rates = payload.get("rates")
    if not isinstance(rates, dict):
        return []

    date = _as_date(payload)
    matches: list[RateMatch] = []
    for quote_cur in quote_curs:
        raw_rate = rates.get(quote_cur)
        if raw_rate is None:
            continue
        try:
            rate = float(raw_rate)
        except (TypeError, ValueError):
            continue
        matches.append(RateMatch(
            base_cur=base_cur, quote_cur=quote_cur, rate=rate,
            amount=amount, converted=amount * rate, date=date,
            url=f"{base}/latest/{base_cur}",
        ))
    return matches


async def _find_fallback_rate(query: str) -> RateMatch | None:
    """The single matched rate for a two-currency gap question, else None.

    Same contract as frankfurter._find_rate, and the SAME RateMatch type, so
    live_data.py builds the source, the observation and the evidence from one
    object either way — the narrative and any chart cannot disagree about the
    number, whichever source supplied it."""
    matches = await _find_fallback_rates(query)
    return matches[0] if matches else None


def _build_source(match: RateMatch) -> WebSource:
    snippet = (
        f"Live market exchange rate (open.er-api.com), last updated {match.date}: "
        f"1 {match.base_cur} = {match.rate:g} {match.quote_cur}. "
        f"{match.amount:g} {match.base_cur} = {match.converted:g} {match.quote_cur}. "
        f"This is a market rate, NOT an official central-bank reference rate: "
        f"the ECB does not publish {match.base_cur}/{match.quote_cur}."
    )
    return WebSource(
        title=f"open.er-api.com — {match.base_cur}/{match.quote_cur} exchange rate ({match.date})",
        url=match.url,
        snippet=snippet,
        provider=PROVIDER,
        freshness="delayed",
        observation=LiveObservation(
            observation_id=f"obs_{uuid.uuid4().hex}",
            indicator=f"{match.base_cur}/{match.quote_cur} exchange rate",
            value=str(match.rate), unit=f"{match.quote_cur} per {match.base_cur}",
            period=match.date, provider=PROVIDER,
            source_url=match.url, freshness="delayed",
        ),
    )
