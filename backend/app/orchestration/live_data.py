"""
Live structured-data grounding for Ask Kriton™.

SearXNG is great for text (rules, procedures, explanations) but not for exact
numbers. This module adds precise-figure sources that answer the question when
one applies, and stays out of the way otherwise:
  - Frankfurter → live currency exchange rates (frankfurter.py)
  - DBnomics    → official economic statistics (dbnomics.py)

Both connectors self-gate (each returns [] unless the question matches its kind)
and fail soft, so this is safe to always call. Results are WebSource objects,
identical in shape to SearXNG hits, so they merge into the existing grounded
answer pipeline (grounding context + [REF-N] source panel) with no other change.
"""
from __future__ import annotations

import asyncio

from app.orchestration.websearch import WebSource
from app.orchestration.frankfurter import fetch_fx
from app.orchestration.dbnomics import fetch_stats


async def fetch_live_data(query: str) -> list[WebSource]:
    """Run the exact-figure connectors concurrently and return their combined
    sources (usually 0–2). Never raises — a failing connector yields nothing."""
    results = await asyncio.gather(fetch_fx(query), fetch_stats(query), return_exceptions=True)
    sources: list[WebSource] = []
    for r in results:
        if isinstance(r, list):
            sources.extend(r)
    return sources
