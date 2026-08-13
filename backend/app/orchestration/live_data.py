"""
Live structured-data grounding for Ask Kriton™.

SearXNG is great for text (rules, procedures, explanations) but not for exact
numbers. This module adds precise-figure sources that answer the question when
one applies, and stays out of the way otherwise:
  - Frankfurter → live currency exchange rates (frankfurter.py)
  - DBnomics    → official economic statistics (dbnomics.py)
  - SEC EDGAR   → US registrants' own filed financials (sec_edgar.py)
  - Market data → quotes, price history, fundamentals, company profiles and UK
                  statutory filings, via Companies House / Finnhub / Polygon /
                  Alpha Vantage (market_data.py)

Every connector self-gates (each returns [] unless the question matches its kind)
and fails soft under a per-connector time cap (see the _*_TIMEOUT values below),
so this is safe to always call. Results are WebSource objects,
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
from dataclasses import dataclass, field

from app.orchestration.websearch import WebSource
from app.orchestration.sec_edgar import fetch_sec_facts
from app.orchestration.market_data import (
    fetch_market_sources, _find_ownership, _build_ownership_source,
)
from app.orchestration.evidence import EvidenceModel, Observation
from app.orchestration.frankfurter import _find_rate, _build_source as _build_fx_source
from app.orchestration.dbnomics import (
    _find_best_series, _build_source as _build_stats_source,
    _find_two_series, _build_pair_source,
)


# Each connector self-gates and fails soft, but "fails soft" says nothing about
# how LONG it may take. dbnomics.py's series search issues several sequential
# requests, each with its own 8s HTTP timeout and no overall cap, so a query it
# ultimately can't resolve was measured spending ~30s (worst observed: 84s
# under gather contention) to return nothing at all. gather() below waits for
# its slowest member and service.py awaits the whole thing before composing, so
# that wall clock became the user's time-to-answer. One overall cap per
# connector stops a slow source from gating an answer the other five already
# have data for.
# Per-connector rather than one shared number: these have genuinely different
# honest costs, and a single cap tight enough to stop DBnomics also truncated
# SEC EDGAR mid-flight — measured turning a working 1-source answer into 0. Each
# value is "comfortably above what this connector costs when it is working",
# not a performance target.
_FX_TIMEOUT = 5.0          # one request against a small, fast endpoint
_STATS_TIMEOUT = 10.0      # dbnomics: several sequential series-search requests
_OWNERSHIP_TIMEOUT = 8.0   # Companies House search + PSC lookup
_SEC_TIMEOUT = 15.0        # sequential candidate-tag probing; ~8.5s warm, ~13s cold
_MARKET_TIMEOUT = 10.0     # provider fallback chain may try more than one vendor


async def _capped(coro, seconds: float):
    """Run one connector under an overall time cap.

    Returns None on timeout or failure — the same "contributed nothing" outcome
    the callers below already handle, so a slow connector degrades exactly like
    a broken one rather than becoming everyone's problem.

    The cap bounds awaitable time, not event-loop-blocking work: a connector
    doing a large synchronous parse (SEC's registrant index, cold) can still
    overshoot, because wait_for cannot interrupt code that never yields.

    asyncio.CancelledError is deliberately not caught: it inherits from
    BaseException, so cancelling the enclosing request still propagates instead
    of being silently converted into a missing source.
    """
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except Exception:
        return None


@dataclass
class LiveDataResult:
    sources: list[WebSource] = field(default_factory=list)
    evidence: EvidenceModel = field(default_factory=EvidenceModel)


async def fetch_live_data(query: str) -> LiveDataResult:
    """Run the exact-figure connectors concurrently. Never raises — a failing
    connector contributes nothing to either the sources or the evidence.

    _find_best_series self-guards against correlation-shaped queries (defers
    entirely to _find_two_series — see dbnomics.py), so all three connectors
    can run concurrently without one path double-populating evidence for the
    same query."""
    fx_match, series_match, pair_match, ownership_match, sec_sources, market_sources = await asyncio.gather(
        _capped(_find_rate(query), _FX_TIMEOUT),
        _capped(_find_best_series(query), _STATS_TIMEOUT),
        _capped(_find_two_series(query), _STATS_TIMEOUT),
        _capped(_find_ownership(query), _OWNERSHIP_TIMEOUT),
        _capped(fetch_sec_facts(query), _SEC_TIMEOUT),
        _capped(fetch_market_sources(query), _MARKET_TIMEOUT),
        return_exceptions=True,
    )
    if isinstance(fx_match, BaseException):
        fx_match = None
    if isinstance(series_match, BaseException):
        series_match = None
    if isinstance(pair_match, BaseException):
        pair_match = None
    if isinstance(ownership_match, BaseException):
        ownership_match = None
    sources: list[WebSource] = []
    evidence = EvidenceModel()

    if fx_match:
        sources.append(_build_fx_source(fx_match))
        evidence.subject = evidence.subject or f"{fx_match.base_cur}/{fx_match.quote_cur} exchange rate"
        evidence.observations.append(Observation(dimension=fx_match.date, value=fx_match.rate, measure="rate"))
        evidence.dimensions.append("date")
        evidence.measures.append("rate")
        evidence.units.append(fx_match.quote_cur)
        evidence.sources.append(fx_match.url)

    if series_match:
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

    # These newly-pulled connectors currently expose grounded WebSources but
    # not chart-ready EvidenceModel observations. Preserve their source output
    # while the existing FX/economic-stat paths continue to populate both.
    if isinstance(sec_sources, list):
        sources.extend(sec_sources)
    if isinstance(market_sources, list):
        sources.extend(market_sources)

    return LiveDataResult(sources=sources, evidence=evidence)
