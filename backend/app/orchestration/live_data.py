"""
Live structured-data grounding for Ask Kriton™.

SearXNG is great for text (rules, procedures, explanations) but not for exact
numbers. This module adds precise-figure sources that answer the question when
one applies, and stays out of the way otherwise:
  - Frankfurter → live currency exchange rates (frankfurter.py)
  - FRED        → official US economic statistics (fred.py)
  - DBnomics    → official economic statistics (dbnomics.py)
  - SEC EDGAR   → US registrants' own filed financials (sec_edgar.py)
  - Market data → quotes, price history, fundamentals, company profiles and UK
                  statutory filings, via Companies House / Finnhub / Polygon /
                  Alpha Vantage (market_data.py)

Every connector self-gates (each returns [] unless the question matches its kind)
and fails soft, so this is safe to always call. Results are WebSource objects,
identical in shape to SearXNG hits, so they merge into the existing grounded
answer pipeline (grounding context + [REF-N] source panel) with no other change.

Each connector's match is fetched exactly ONCE (via its private `_find_*`
finder) and used to build BOTH the WebSource text and the structured
EvidenceModel below — never two independent fetches for the same fact, so the
narrative text and any visualization built from `evidence` can never disagree
about the underlying numbers (see evidence.py's module docstring).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.domains.model_gateway.tools.chart_tool import ChartToolError, build_chart_fence
from app.orchestration.websearch import WebSource, wants_visual
from app.orchestration.sec_edgar import fetch_sec_facts
from app.orchestration.legislation import fetch_legislation
from app.orchestration.market_data import (
    fetch_market_sources, _find_ownership, _build_ownership_source,
)
from app.orchestration.evidence import EvidenceModel, Observation, OHLCBar
from app.orchestration.frankfurter import (
    _find_rate, _build_source as _build_fx_source, unsupported_currency_note,
)
from app.orchestration.fred import _find_fred_series, _build_source as _build_fred_source
from app.orchestration.dbnomics import (
    _find_best_series, _build_source as _build_stats_source,
    _find_two_series, _build_pair_source,
)

settings = get_settings()


@dataclass
class LiveDataResult:
    sources: list[WebSource] = field(default_factory=list)
    evidence: EvidenceModel = field(default_factory=EvidenceModel)
    deterministic_answer: str | None = None


async def fetch_live_data(query: str) -> LiveDataResult:
    """Run the exact-figure connectors concurrently. Never raises — a failing
    connector contributes nothing to either the sources or the evidence.

    _find_best_series self-guards against correlation-shaped queries (defers
    entirely to _find_two_series — see dbnomics.py), so all three connectors
    can run concurrently without one path double-populating evidence for the
    same query. One total deadline bounds the whole fan-out: every connector
    that has not finished within it is cancelled, and everything that did
    finish is still kept."""
    connectors = (
        _find_rate(query), _find_fred_series(query), _find_best_series(query),
        _find_two_series(query), _find_ownership(query), fetch_sec_facts(query),
        fetch_market_sources(query), fetch_legislation(query),
    )
    tasks = [asyncio.ensure_future(connector) for connector in connectors]
    pending: set[asyncio.Future] = set(tasks)
    try:
        done, pending = await asyncio.wait(
            tasks, timeout=settings.LIVE_DATA_TIMEOUT_SECONDS
        )
    finally:
        # A total deadline or parent-request cancellation must stop every
        # unfinished connector, including provider retries and backoff sleeps.
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    results: list[object | None] = [None] * len(tasks)
    for index, task in enumerate(tasks):
        if task.cancelled() or task.exception() is not None:
            continue
        results[index] = task.result()

    fx_match, fred_match, series_match, pair_match = results[0:4]
    ownership_match, sec_sources, market_sources, legislation_sources = results[4:8]
    sources: list[WebSource] = []
    evidence = EvidenceModel()

    if not fx_match:
        # No rate, but the question may have named a currency the ECB simply
        # does not publish. Say so as a source rather than leaving the gap for
        # the model to fill from memory (frankfurter.py's docstring records
        # the fabrication this prevents).
        fx_gap = unsupported_currency_note(query)
        if fx_gap:
            sources.append(fx_gap)

    if fx_match:
        sources.append(_build_fx_source(fx_match))
        evidence.subject = evidence.subject or f"{fx_match.base_cur}/{fx_match.quote_cur} exchange rate"
        evidence.observations.append(Observation(dimension=fx_match.date, value=fx_match.rate, measure="rate"))
        evidence.dimensions.append("date")
        evidence.measures.append("rate")
        evidence.units.append(fx_match.quote_cur)
        evidence.sources.append(fx_match.url)

    # FRED is authoritative for the curated US series it recognizes.  When it
    # succeeds, suppress the concurrently-fetched DBnomics alternative so one
    # answer never mixes two differently-defined series under one chart.
    if fred_match:
        sources.append(_build_fred_source(fred_match))
        evidence.subject = evidence.subject or fred_match.series_name
        evidence.observations.extend(
            Observation(dimension=period, value=value, measure=fred_match.series_name)
            for period, value in fred_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(fred_match.series_name)
        evidence.units.append(fred_match.unit)
        evidence.sources.append(fred_match.url)
        evidence.provider = "Federal Reserve Bank of St. Louis (FRED)"
        evidence.series_id = fred_match.series_id
        evidence.requested_start = fred_match.requested_start
        evidence.requested_end = fred_match.requested_end
        evidence.retrieved_start = fred_match.points[0][0]
        evidence.retrieved_end = fred_match.points[-1][0]
        evidence.coverage_complete = fred_match.coverage_complete
        if fred_match.warning:
            evidence.warnings.append(fred_match.warning)

    if series_match and not fred_match:
        sources.append(_build_stats_source(series_match))
        evidence.subject = evidence.subject or series_match.series_name
        evidence.observations.extend(
            Observation(dimension=p, value=v, measure=series_match.series_name)
            for p, v in series_match.points
        )
        evidence.dimensions.append("period")
        evidence.measures.append(series_match.series_name)
        evidence.sources.append(series_match.url)

    if pair_match:
        match_a, match_b = pair_match
        sources.append(_build_pair_source(match_a, match_b))
        evidence.subject = evidence.subject or match_a.series_name
        evidence.secondary_subject = match_b.series_name
        evidence.observations.extend(
            Observation(dimension=p, value=v, measure=match_a.series_name) for p, v in match_a.points
        )
        evidence.secondary_observations.extend(
            Observation(dimension=p, value=v, measure=match_b.series_name) for p, v in match_b.points
        )
        evidence.dimensions.append("period")
        evidence.measures.extend([match_a.series_name, match_b.series_name])
        evidence.sources.extend([match_a.url, match_b.url])

    if ownership_match:
        sources.append(_build_ownership_source(ownership_match))
        evidence.composition_subject = f"{ownership_match.company_name} — shareholding"
        evidence.composition.extend(
            Observation(dimension=label, value=value, measure="ownership_percent")
            for label, value in ownership_match.slices
        )
        evidence.composition_caveat = ownership_match.caveat
        evidence.sources.append(ownership_match.url)

    # SEC EDGAR currently exposes grounded WebSources but not chart-ready
    # EvidenceModel observations — preserve its source output only.
    if isinstance(sec_sources, list):
        sources.extend(sec_sources)
        deterministic_answer = (
            "\n\n".join(source.snippet for source in sec_sources[:3])
            if sec_sources else None
        )
    else:
        deterministic_answer = None
    if isinstance(legislation_sources, list):
        sources.extend(legislation_sources)

    # market_data.py's fetch_market_sources() populates BOTH sources and (for
    # a history-shaped question) real OHLC bars from the SAME single fetch —
    # every other market-data intent (quote/fundamentals/filings/profile)
    # still contributes sources only, unchanged.
    if market_sources is not None:
        sources.extend(market_sources.sources)
        if market_sources.ohlc:
            evidence.ohlc_subject = market_sources.symbol or evidence.ohlc_subject
            evidence.ohlc.extend(
                OHLCBar(
                    dimension=bar.timestamp, open=bar.open, high=bar.high,
                    low=bar.low, close=bar.close, volume=bar.volume,
                )
                for bar in market_sources.ohlc
            )

        if market_sources.sources and deterministic_answer is None:
            deterministic_answer = market_sources.sources[0].snippet

    return LiveDataResult(
        sources=sources,
        evidence=evidence,
        deterministic_answer=deterministic_answer,
    )


# "last 3 years", "past 5 years", "previous 10 quarters" — how much history the
# question actually asked for. dbnomics.py's connector always returns up to its
# own MAX_POINTS (20) regardless of what was asked, so without this a "last 3
# years" request silently charts two decades of data instead.
_REQUESTED_PERIOD_COUNT = re.compile(r"\b(?:last|past|previous)\s+(\d+)\s*(?:years?|yrs?|quarters?)\b", re.I)


def _requested_period_count(query: str) -> int | None:
    match = _REQUESTED_PERIOD_COUNT.search(query)
    return int(match.group(1)) if match else None


def build_forced_chart(query: str, sources: list[WebSource]) -> str | None:
    """Build a ```chart fence directly from a connector's own fetched numeric
    series, when the question asked for a visual and the data supports one.

    This exists because chart correctness cannot depend solely on the model
    choosing to draw one: "Compare GDP growth for the UK, US and Germany" is
    exactly the shape dbnomics.fetch_stats() answers with real per-country
    time series, but nothing forced the model to turn that into a chart
    rather than a prose table (or a table it wrote in markdown) — the
    render_chart tool (chart_tool.py) fixes a model-*chosen* chart's
    correctness, not whether a chart gets made at all. The caller only uses
    this fence when composed_text has none already, so a chart the model (or
    tool) already produced is never overridden.
    """
    if not wants_visual(query):
        return None
    stat_sources = [s for s in sources if s.series and len(s.series) >= 2]
    if not stat_sources:
        return None
    period_count = _requested_period_count(query)
    if period_count and period_count >= 2:
        stat_sources = [dataclasses.replace(s, series=s.series[-period_count:]) for s in stat_sources]

    if len(stat_sources) == 1:
        source = stat_sources[0]
        args = {
            "type": "line",
            "title": source.title,
            "categories": [period for period, _ in source.series],
            "series": [{"name": source.title, "data": [value for _, value in source.series]}],
        }
    else:
        # A comparison: chart only the periods every source actually has, so
        # a country with a shorter reporting lag doesn't get padded with a
        # value it never reported.
        common_periods = set(period for period, _ in stat_sources[0].series)
        for source in stat_sources[1:]:
            common_periods &= set(period for period, _ in source.series)
        ordered_periods = sorted(common_periods)
        if len(ordered_periods) < 1:
            return None
        series = []
        for source in stat_sources:
            values_by_period = dict(source.series)
            label = source.title.rsplit("—", 1)[-1].strip() if "—" in source.title else source.title
            series.append({"name": label, "data": [values_by_period[period] for period in ordered_periods]})
        args = {
            "type": "bar",
            "title": stat_sources[0].title.rsplit("—", 1)[0].strip() if "—" in stat_sources[0].title else "Comparison",
            "categories": ordered_periods,
            "series": series,
        }

    try:
        return build_chart_fence(json.dumps(args))
    except ChartToolError:
        return None
