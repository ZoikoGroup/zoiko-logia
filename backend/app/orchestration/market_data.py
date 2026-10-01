"""Market and company data grounding for Ask Kriton™.

The bridge between app/domains/market_data/ and the answer pipeline, and
deliberately thin: it self-gates, calls the domain service, and renders the
normalized result into the same WebSource shape SearXNG, DBnomics and
Frankfurter return. No provider-specific code lives here — adding a fifth
provider must not require editing this file.

Same contract as the other exact-figure connectors (dbnomics.py,
frankfurter.py, sec_edgar.py):
  - self-gating: returns [] unless the question is actually about market or
    company data, so a question about depreciation never gets a share price
    attached as provenance
  - fail-soft: any error yields [], and the bot falls back to its normal
    web-grounded answer

Freshness is carried through to the citation rather than flattened away. A
previous close and a realtime tick are different claims, and an answer that
blurs them is the specific failure this product exists to avoid — so the
snippet states it in words and WebSource.freshness states it in a field the UI
can badge.

Streaming is NOT handled here. A continuous price feed has no query to
classify, no answer to validate and nothing to audit before returning, so it
cannot travel this path — see the market_data package docstring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domains.calculations.schemas import LiveObservation
from app.domains.market_data import identity, registry, service
from app.domains.market_data.http import make_client
from app.domains.market_data.identity import company_name_hint, resolve_local
from app.domains.market_data.providers.companies_house import CompaniesHouseProvider
from app.domains.market_data.schemas import (
    CompanyProfile,
    EntityRef,
    FilingRecord,
    FinancialMetric,
    OHLCVBar,
    ProviderBadResponse,
    ProviderError,
    StockQuote,
)
from app.orchestration.websearch import WebSource

# How each freshness value should read to a human. The reader must never have
# to infer whether a figure is live.
_FRESHNESS_WORDS = {
    "realtime": "real-time",
    "delayed": "delayed (not real-time)",
    "historical": "historical / end-of-day (not real-time)",
    "filing": "as filed with the registrar",
}


def _money(value: float | None, currency: str = "") -> str:
    if value is None:
        return "n/a"
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{value:,.2f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{prefix}{value:,.0f}"


def _number_text(value: Optional[float]) -> str:
    """Render a fetched number at full precision, without exponent notation.

    The structured observation is what charts, evidence and the audit record read,
    so it must not be rounded for display. Two earlier attempts were both wrong
    in a different direction: `f"{value:g}"` silently drops a significant digit
    from an index level (24312.44 became "24312.4"), and a fixed twelve-decimal
    format exposes binary floating-point noise (24312.439999999999). Python's
    repr is the shortest string that round-trips to the same float, which is
    exactly the precision the value actually carries; the fixed-width branch only
    exists so a very small or very large number never reaches a consumer as
    "2.4312e+04".
    """
    if value is None:
        return ""
    text = repr(float(value))
    if "e" in text or "E" in text:
        text = f"{value:.12f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
    return text


def _quote_source(quote: StockQuote) -> WebSource:
    # Only name the company separately when we actually have a name — the
    # provider quote endpoints often return none, and "AAPL (AAPL)" reads as a
    # bug rather than as data.
    label = f"{quote.company_name} ({quote.symbol})" if quote.company_name else quote.symbol
    bits = [f"{label}: {_money(quote.price, quote.currency)}"]
    if quote.change is not None and quote.change_percent is not None:
        bits.append(f"change {quote.change:+,.2f} ({quote.change_percent:+.2f}%)")
    for label, value in (("open", quote.open), ("high", quote.high), ("low", quote.low),
                         ("previous close", quote.previous_close)):
        if value is not None:
            bits.append(f"{label} {_money(value, quote.currency)}")
    if quote.volume is not None:
        bits.append(f"volume {quote.volume:,.0f}")

    freshness_words = _FRESHNESS_WORDS.get(quote.freshness, quote.freshness)
    stamp = quote.provider_timestamp or quote.fetched_at
    snippet = (
        f"{'; '.join(bits)}. "
        f"Data is {freshness_words}, from {quote.provider} as at {stamp}."
        + (f" Market state: {quote.market_status}." if quote.market_status else "")
    )
    return WebSource(
        title=f"{quote.provider} — {quote.symbol} quote ({quote.freshness})"[:200],
        url=quote.source_url,
        snippet=snippet,
        provider=quote.provider,
        fetched_at=quote.fetched_at,
        freshness=quote.freshness,
        observation=LiveObservation(
            observation_id=f"{quote.provider}:{quote.symbol}",
            indicator=quote.symbol,
            value=_number_text(quote.price),
            unit=quote.currency or "index_points",
            period=(quote.provider_timestamp or quote.fetched_at or "")[:19],
            provider=quote.provider,
            source_url=quote.source_url,
            freshness=quote.freshness,
        ),
    )


# Raw interval keys are the providers' wire values ("1mo"), not words a reader
# should have to decode in an answer that is otherwise plain English.
_INTERVAL_WORDS = {"1d": "daily", "1w": "weekly", "1mo": "monthly",
                   "1h": "hourly", "5m": "5-minute"}


def _history_source(bars: list[OHLCVBar]) -> WebSource:
    first, last = bars[0], bars[-1]
    tail = bars[-8:]
    series = ", ".join(f"{b.timestamp[:10]}: {b.close:,.2f}" for b in tail)
    cadence = _INTERVAL_WORDS.get(last.interval or "1d", last.interval or "daily")
    return WebSource(
        title=f"{last.provider} — {last.symbol} price history ({first.timestamp[:10]} to {last.timestamp[:10]})"[:200],
        url=f"https://www.google.com/finance/quote/{last.symbol}",
        snippet=(
            f"{last.symbol} {cadence} closes, {len(bars)} bars from "
            f"{first.timestamp[:10]} to {last.timestamp[:10]}. Most recent — {series}. "
            f"Historical end-of-day data from {last.provider}; not real-time."
        ),
        provider=last.provider,
        freshness="historical",
    )


def _metric_value(metric: FinancialMetric) -> str:
    """A figure a reader can take in at a glance.

    Plain %g turned a 1.3-trillion market cap into "1.307e+06" — technically
    correct, useless in an answer, and the kind of thing that gets misread by
    three orders of magnitude. Large currency amounts get a scale word
    alongside the separated digits; ratios and percentages stay compact.
    """
    value, unit = metric.value, metric.unit
    if unit == "%":
        return f"{value:,.2f}%"
    if unit in ("ratio", ""):
        return f"{value:,.4g}" if abs(value) < 1000 else f"{value:,.2f}"
    if unit == "per share":
        return f"{value:,.2f} per share"

    # Currency amount.
    for threshold, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(value) >= threshold:
            return f"{unit} {value:,.0f} ({value / threshold:,.2f} {word})".strip()
    return f"{unit} {value:,.2f}".strip()


def _fundamentals_source(metrics: list[FinancialMetric]) -> WebSource:
    head = metrics[0]
    lines = "; ".join(f"{m.metric}: {_metric_value(m)}" for m in metrics)
    return WebSource(
        title=f"{head.provider} — {head.company or head.symbol} key figures"[:200],
        url=head.source_url,
        snippet=(
            f"Reported figures for {head.company or head.symbol}"
            f"{f' ({head.symbol})' if head.symbol else ''}: {lines}. "
            f"Source: {head.provider}"
            f"{f', fiscal period {head.fiscal_period}' if head.fiscal_period else ''}. "
            "These are provider-computed metrics, not audited statements."
        ),
        provider=head.provider,
        freshness="historical",
    )


def _filings_source(filings: list[FilingRecord]) -> WebSource:
    head = filings[0]
    lines = "; ".join(
        f"{f.filing_date}: {f.filing_type} — {f.description}".strip().rstrip("—").strip() for f in filings[:8]
    )
    # Name the registry that actually answered. This used to hardcode
    # "Companies House" in the title and the snippet, so a filing record from any
    # other register — an SEC EDGAR filing reached through the same intent — was
    # presented to the user as if the UK registrar had produced it. A provenance
    # line that asserts the wrong publisher is worse than no publisher at all.
    registry_label = {
        "companies_house": "Companies House",
        "sec_edgar": "SEC EDGAR",
    }.get(head.provider or "", head.provider or "the filing registry")
    number_clause = (
        f" (company number {head.company_number})" if head.company_number else ""
    )
    return WebSource(
        title=f"{registry_label} — {head.company_name} filing history"[:200],
        url=head.source_url,
        snippet=(
            f"{head.company_name}{number_clause}, most recent statutory "
            f"filings as recorded at {registry_label}: {lines}. "
            f"As filed with the registrar; filing dates are the dates received."
        ),
        provider=head.provider,
        freshness="filing",
    )


def _profile_source(profile: CompanyProfile) -> WebSource:
    facts = [f"{k.replace('_', ' ')}: {v}" for k, v in (profile.identifiers or {}).items() if v]
    for label, value in (("exchange", profile.exchange), ("country", profile.country),
                         ("sector", profile.sector), ("industry", profile.industry)):
        if value:
            facts.append(f"{label}: {value}")
    if profile.market_cap is not None:
        facts.append(f"market capitalisation: {profile.market_cap:,.0f} {profile.currency}".strip())

    return WebSource(
        title=f"{profile.provider} — {profile.company_name} company profile"[:200],
        url=profile.source_url,
        snippet=f"{profile.company_name}"
        f"{f' ({profile.symbol})' if profile.symbol else ''}. "
        + ". ".join(facts)
        + f". Source: {profile.provider}.",
        provider=profile.provider,
        freshness="filing" if profile.provider == "companies_house" else "historical",
    )


def source_for_result(intent: str, result) -> WebSource | None:
    try:
        if intent == registry.INTENT_QUOTE and isinstance(result, StockQuote):
            return _quote_source(result)
        # An index level IS a quote — the service resolves the index intent to a
        # StockQuote from the keyless index_quote provider, and this is what
        # builds its citation. Without the branch, "What is the S&P 500?" came
        # back with nothing: the intent was detected and fetched, but no source
        # was ever rendered for it.
        if intent == registry.INTENT_INDEX and isinstance(result, StockQuote):
            return _quote_source(result)
        if intent == registry.INTENT_HISTORY and isinstance(result, list) and result:
            return _history_source(result)
        if intent == registry.INTENT_FUNDAMENTALS and isinstance(result, list) and result:
            return _fundamentals_source(result)
        if intent == registry.INTENT_FILINGS and isinstance(result, list) and result:
            return _filings_source(result)
        if isinstance(result, CompanyProfile):
            return _profile_source(result)
    except Exception:  # noqa: BLE001 — rendering must never break the request
        return None
    return None


async def fetch_market_sources(query: str) -> MarketSourceResult:
    """Return grounding sources (and, for a history-shaped question, the
    real OHLC bars behind them) for a market/company question, else an
    empty result. Fetched exactly once — the SAME result builds both the
    WebSource citation and (for history) the chart-ready evidence, never two
    independent fetches for the same fact (see evidence.py's docstring)."""
    companies = identity.find_all_known_names(query)
    if len(companies) >= 2:
        # A question naming two or more well-known companies ("Compare Apple and
        # Microsoft...") is a comparison, not a single-entity lookup — routed to
        # fetch_market_data_for_companies() so both get fetched and grounded,
        # rather than resolving to whichever one company the single-entity path
        # happened to match first and silently dropping the rest.
        results = await service.fetch_market_data_for_companies(query, companies)
        sources = [source_for_result(intent, result) for result, _provider, intent, _label in results]
        return [s for s in sources if s is not None]

    outcome = await service.fetch_market_data(query)
    if outcome is None:
        return MarketSourceResult()

    result, _provider, intent = outcome
    source = source_for_result(intent, result)
    return [source] if source is not None else []
