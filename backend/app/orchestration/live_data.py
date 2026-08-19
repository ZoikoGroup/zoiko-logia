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
and fails soft, so this is safe to always call. Results are WebSource objects,
identical in shape to SearXNG hits, so they merge into the existing grounded
answer pipeline (grounding context + [REF-N] source panel) with no other change.
"""
from __future__ import annotations

import asyncio

from app.orchestration.websearch import WebSource
from app.orchestration.frankfurter import fetch_fx
from app.orchestration.dbnomics import fetch_stats
from app.orchestration.sec_edgar import fetch_sec_facts
from app.orchestration.market_data import fetch_market_sources
from app.orchestration.legislation import fetch_legislation
from app.orchestration.statistics import analyse_statistical_query
from app.orchestration.statistics.render import statistical_sources


async def fetch_live_data(query: str) -> list[WebSource]:
    """Run the exact-figure connectors concurrently and return their combined
    sources (usually 0–4). Never raises — a failing connector yields nothing."""
    # Structured statistical analysis is provider-independent and preserves
    # observations as typed series through alignment/calculation.  It replaces
    # the legacy one-series DBnomics lookup whenever it recognizes a supported
    # analytical request; ordinary statistic lookups retain the legacy path.
    statistical_attempt, *results = await asyncio.gather(
        analyse_statistical_query(query),
        fetch_fx(query),
        fetch_sec_facts(query),
        fetch_market_sources(query),
        fetch_legislation(query),
        return_exceptions=True,
    )
    sources: list[WebSource] = []
    for r in results:
        if isinstance(r, list):
            sources.extend(r)
    if not isinstance(statistical_attempt, Exception) and statistical_attempt.handled:
        sources.extend(statistical_sources(statistical_attempt))
    else:
        # Backward-compatible path for simple single-series questions that the
        # structured planner intentionally does not claim.
        try:
            sources.extend(await fetch_stats(query))
        except Exception:
            pass
    return sources
