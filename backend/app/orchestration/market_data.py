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

from app.domains.market_data import registry, service
from app.domains.market_data.schemas import (
    CompanyProfile,
    FilingRecord,
    FinancialMetric,
    OHLCVBar,
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
    )


def _history_source(bars: list[OHLCVBar]) -> WebSource:
    first, last = bars[0], bars[-1]
    tail = bars[-8:]
    series = ", ".join(f"{b.timestamp[:10]}: {b.close:,.2f}" for b in tail)
    return WebSource(
        title=f"{last.provider} — {last.symbol} price history ({first.timestamp[:10]} to {last.timestamp[:10]})"[:200],
        url=f"https://www.google.com/finance/quote/{last.symbol}",
        snippet=(
            f"{last.symbol} {last.interval or 'daily'} closes, {len(bars)} bars from "
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
    return WebSource(
        title=f"Companies House — {head.company_name} filing history"[:200],
        url=head.source_url,
        snippet=(
            f"{head.company_name} (company number {head.company_number}), most recent statutory "
            f"filings as recorded at Companies House: {lines}. "
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


async def fetch_market_sources(query: str) -> list[WebSource]:
    """Return grounding sources for a market/company question, else []."""
    outcome = await service.fetch_market_data(query)
    if outcome is None:
        return []

    result, _provider, intent = outcome
    try:
        if intent == registry.INTENT_QUOTE and isinstance(result, StockQuote):
            return [_quote_source(result)]
        if intent == registry.INTENT_HISTORY and isinstance(result, list) and result:
            return [_history_source(result)]  # type: ignore[arg-type]
        if intent == registry.INTENT_FUNDAMENTALS and isinstance(result, list) and result:
            return [_fundamentals_source(result)]  # type: ignore[arg-type]
        if intent == registry.INTENT_FILINGS and isinstance(result, list) and result:
            return [_filings_source(result)]  # type: ignore[arg-type]
        if isinstance(result, CompanyProfile):
            return [_profile_source(result)]
    except Exception:  # noqa: BLE001 — rendering must never break the request
        return []
    return []
