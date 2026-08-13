"""Provider-independent models and error types.

Everything leaving a provider adapter is one of these, so the registry, the
service and the answer pipeline never depend on a provider's response shape.
Adding a fifth provider must not require touching anything downstream.

Plain dataclasses rather than pydantic models: these are internal to the
backend and never cross the API boundary — the pipeline serialises them into a
WebSource snippet. Matching orchestration/websearch.py's WebSource, which is
also a dataclass for the same reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Freshness ────────────────────────────────────────────────────────────────
# Kept as explicit strings rather than a bool "is_live", because the difference
# between a realtime tick, a 15-minute-delayed quote and yesterday's close is
# exactly the thing a finance answer must not blur. A provider states what it
# actually returned; the composer surfaces it verbatim.
FRESHNESS_REALTIME = "realtime"
FRESHNESS_DELAYED = "delayed"
FRESHNESS_HISTORICAL = "historical"
FRESHNESS_FILING = "filing"          # as-filed statutory data (Companies House, SEC)

_VALID_FRESHNESS = {
    FRESHNESS_REALTIME,
    FRESHNESS_DELAYED,
    FRESHNESS_HISTORICAL,
    FRESHNESS_FILING,
}


# ── Errors ───────────────────────────────────────────────────────────────────
# Distinct types because the retry policy differs per class: a rate limit is
# worth backing off on, a bad key never is. http.py keys its retry decision off
# these, so a provider that returns 401 forever is not hammered.

class ProviderError(Exception):
    """Base for every provider failure. Carries the provider name so a caller
    that swallows one still knows which source went quiet."""

    def __init__(self, provider: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


class ProviderNotConfigured(ProviderError):
    """No API key set. Not an outage — the operator simply has not enabled it."""


class ProviderAuthError(ProviderError):
    """401/403. Never retried: a rejected key is rejected consistently."""


class ProviderRateLimited(ProviderError):
    """429, or a provider that signals throttling in a 200 body (Alpha Vantage
    does exactly this). retry_after is seconds, when the provider states it."""

    def __init__(self, provider: str, message: str, retry_after: Optional[float] = None):
        super().__init__(provider, message)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """5xx, timeout, or connection failure. Retried with backoff."""


class ProviderBadResponse(ProviderError):
    """200 with a body that does not parse or is missing required fields."""


class CapabilityNotSupported(ProviderError):
    """The provider genuinely cannot serve this intent (Companies House has no
    quotes; Alpha Vantage has no UK filings). Signals the registry to move to
    the next provider rather than treating it as an outage."""


# ── Normalized models ────────────────────────────────────────────────────────

@dataclass
class EntityRef:
    """Who a question is about, in whatever identifiers we could resolve.

    One entity has different keys in different systems — Barclays is company
    number 01026167 at Companies House, ticker BCS on NYSE, BARC.L in London.
    Carrying them together is what lets one question combine filings with
    market data.
    """
    name: str = ""
    ticker: str = ""
    company_number: str = ""      # Companies House (UK)
    cik: str = ""                 # SEC (US)
    exchange: str = ""
    country: str = ""

    def has_any_id(self) -> bool:
        return bool(self.ticker or self.company_number or self.cik)


@dataclass
class StockQuote:
    symbol: str
    price: float
    provider: str
    freshness: str
    fetched_at: str
    company_name: str = ""
    exchange: str = ""
    currency: str = ""
    change: Optional[float] = None
    change_percent: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    previous_close: Optional[float] = None
    volume: Optional[float] = None
    provider_timestamp: str = ""
    market_status: str = ""
    source_url: str = ""


@dataclass
class OHLCVBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    provider: str
    volume: Optional[float] = None
    interval: str = ""
    currency: str = ""
    exchange: str = ""


@dataclass
class CompanyProfile:
    company_name: str
    provider: str
    symbol: str = ""
    exchange: str = ""
    country: str = ""
    currency: str = ""
    industry: str = ""
    sector: str = ""
    market_cap: Optional[float] = None
    website: str = ""
    identifiers: dict[str, str] = field(default_factory=dict)
    source_url: str = ""


@dataclass
class FinancialMetric:
    metric: str
    value: float
    provider: str
    company: str = ""
    symbol: str = ""
    unit: str = ""
    period: str = ""
    fiscal_period: str = ""
    filing_date: str = ""
    currency: str = ""
    source_url: str = ""


@dataclass
class OwnershipStake:
    """One persons-with-significant-control (PSC) entry from Companies House —
    a real, named shareholder and their declared band of control, never an
    exact percentage (the statutory filing itself only ever states a band).

    min_percent/max_percent are None when the PSC's natures_of_control carry
    no ownership-of-shares band at all (e.g. voting-rights-only or
    right-to-appoint-directors entries) — those are real control facts but
    not a share-of-the-whole figure, so callers building a composition view
    must skip stakes with no percent band rather than inventing one.
    """
    name: str
    kind: str                                  # individual|corporate-entity|legal-person|super-secure ...-with-significant-control
    provider: str
    nature_of_control: list[str] = field(default_factory=list)
    min_percent: Optional[float] = None
    max_percent: Optional[float] = None
    notified_on: str = ""
    ceased: bool = False
    company_number: str = ""
    company_name: str = ""
    source_url: str = ""


@dataclass
class FilingRecord:
    company_name: str
    filing_type: str
    filing_date: str
    provider: str
    company_number: str = ""
    period: str = ""
    description: str = ""
    document_id: str = ""
    source_url: str = ""


@dataclass
class ProviderHealth:
    """Never carries credentials — only whether one is present. Surfaced on the
    status endpoint, which is not an authenticated-admin-only surface."""
    provider: str
    configured: bool
    reachable: Optional[bool] = None
    detail: str = ""


def validate_freshness(value: str) -> str:
    """Guard against a provider adapter inventing its own freshness word — the
    composer shows this to the reader verbatim, so an unrecognised value would
    become an unverified claim about how current the figure is."""
    if value not in _VALID_FRESHNESS:
        raise ValueError(f"Unknown freshness {value!r}")
    return value
