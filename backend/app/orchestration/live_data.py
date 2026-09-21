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

from app.core.config import get_settings
from app.orchestration.websearch import WebSource
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
