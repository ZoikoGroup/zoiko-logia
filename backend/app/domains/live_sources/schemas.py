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
    # Company-lookup intents only (SEC EDGAR / Companies House) — the
    # extracted company name/ticker. For these, indicator_code is repurposed
    # as the financial concept to fetch (e.g. "Assets" for SEC EDGAR,
    # "profile" for Companies House) rather than a World Bank-style code.
    company_query: Optional[str] = None
    # Latency optimization (Tier 1): True only for classifier.py's
    # implies_country=True rules ("bank rate", "fed funds rate" — narrow,
    # unambiguous economic-data phrases). orchestration/service.py uses
    # this to skip the ~10-15s Postgres vector search entirely for these
    # queries, since a document match is implausible. Deliberately NOT set
    # for every live-data match (FX, company lookup, generic World Bank
    # indicators like "inflation"/"GDP") — those could legitimately
    # co-occur with a real document question (e.g. "what is UK inflation
    # and how does IFRS require disclosing it"), so document search must
    # still run for them.
    skip_document_search: bool = False


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
    # Propagated from LiveDataIntent.company_query for company-lookup
    # results — needed so live_sources.service.make_live_source_id() can
    # keep two different companies' identical indicator_code from
    # colliding onto the same source_id.
    company_query: Optional[str] = None


class LiveFetchOutcome(BaseModel):
    intent: Optional[LiveDataIntent] = None
    cache_hit: bool = False
    succeeded: bool = False
    error: Optional[str] = None
    normalized: Optional[NormalizedResponse] = None
