"""
Internal contract types for the live/dynamic external data path. These are
connector-facing shapes, not the canonical orchestration contracts —
service.py adapts a NormalizedResponse into a SourceSummary/synthetic chunk
(app.orchestration.schemas) at the boundary where it hands off to the
existing retrieval/citation pipeline.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class LiveDataIntent(BaseModel):
    provider_key: str
    indicator_code: str
    indicator_label: str
    country_code: str
    country_label: str


class NormalizedResponse(BaseModel):
    provider_key: str
    indicator_code: str
    indicator_label: str
    country_code: str
    country_label: str
    value: float | str
    unit: str = ""
    observation_period: str
    as_of: str  # fetch timestamp, ISO 8601
    source_url: str
    citation_title: str


class LiveFetchOutcome(BaseModel):
    intent: Optional[LiveDataIntent] = None
    cache_hit: bool = False
    succeeded: bool = False
    error: Optional[str] = None
    normalized: Optional[NormalizedResponse] = None
