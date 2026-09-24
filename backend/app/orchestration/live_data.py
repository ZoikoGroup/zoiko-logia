"""
Live structured-data grounding for Ask Kriton™.

SearXNG is great for text (rules, procedures, explanations) but not for exact
numbers. This module adds precise-figure sources that answer the question when
one applies, and stays out of the way otherwise:
  - Frankfurter → live currency exchange rates (frankfurter.py)
  - DBnomics    → official economic statistics (dbnomics.py)
  - Market data → stock quotes, price history, fundamentals and company
                  profiles, via Twelve Data (market_data.py)

Every connector self-gates (each returns [] unless the question matches its kind)
and fails soft, so this is safe to always call. Results are WebSource objects,
identical in shape to SearXNG hits, so they merge into the existing grounded
answer pipeline (grounding context + [REF-N] source panel) with no other change.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import re

from app.core.config import get_settings
from app.domains.model_gateway.tools.chart_tool import ChartToolError, build_chart_fence
from app.orchestration.websearch import WebSource, wants_visual
from app.orchestration.frankfurter import fetch_fx
from app.orchestration.dbnomics import fetch_stats
from app.orchestration.market_data import fetch_market_sources

settings = get_settings()


async def fetch_live_data(query: str) -> list[WebSource]:
    """Run the exact-figure connectors concurrently and return their combined
    sources (usually 0–3). Never raises — a failing connector yields nothing."""
    tasks = [
        asyncio.create_task(fetch_fx(query)),
        asyncio.create_task(fetch_stats(query)),
        asyncio.create_task(fetch_market_sources(query)),
    ]
    done: set[asyncio.Task] = set()
    pending: set[asyncio.Task] = set(tasks)
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

    sources: list[WebSource] = []
    for task in done:
        if task.cancelled():
            continue
        try:
            result = task.result()
        except Exception:
            continue
        if isinstance(result, list):
            sources.extend(result)
    return sources


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
