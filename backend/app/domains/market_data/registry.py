"""Intent detection and provider selection.

Two jobs, both pure functions of the query and the environment:

  1. Decide whether a question is even about market/company data. This module
     is the gate — orchestration/market_data.py calls it first, and returns []
     when there is no intent, exactly like dbnomics.py and frankfurter.py
     self-gate. Firing on "explain depreciation" would attach a stranger's
     share price as provenance.

  2. Decide which provider serves that intent, in what order. Routing is a
     table, not scattered if-statements, so changing priority is a data edit
     and the whole policy is readable in one place.

Provider set: Twelve Data serves every market intent (quotes, history,
fundamentals, profiles, symbol search). Company filings have no provider here —
that data (UK Companies House / US SEC statutory records) is not something a
market price API carries — so the filings intent resolves to no provider and
the connector stays silent for it, falling back to the web-grounded answer.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from app.domains.market_data.providers.base import (
    CAP_FILINGS,
    CAP_FUNDAMENTALS,
    CAP_HISTORY,
    CAP_PROFILE,
    CAP_QUOTE,
    CAP_SEARCH,
    BaseStockProvider,
)
from app.domains.market_data.providers.twelve_data import TwelveDataProvider

# ── Intents ──────────────────────────────────────────────────────────────────
INTENT_QUOTE = "stock_quote"
INTENT_HISTORY = "stock_history"
INTENT_FUNDAMENTALS = "stock_fundamentals"
INTENT_PROFILE = "stock_company_profile"
INTENT_FILINGS = "company_filings"
INTENT_LOOKUP = "company_lookup"

INTENT_CAPABILITY = {
    INTENT_QUOTE: CAP_QUOTE,
    INTENT_HISTORY: CAP_HISTORY,
    INTENT_FUNDAMENTALS: CAP_FUNDAMENTALS,
    INTENT_PROFILE: CAP_PROFILE,
    INTENT_FILINGS: CAP_FILINGS,
    INTENT_LOOKUP: CAP_SEARCH,
}

# Order matters: the first pattern that matches wins, so the specific intents
# ("filing history", "share price over the last month") are tested before the
# broad ones ("price").
_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        INTENT_FILINGS,
        re.compile(
            r"\b(filing|filings|filing history|annual return|confirmation statement|"
            r"statutory accounts|companies house|filed accounts)\b",
            re.I,
        ),
    ),
    (
        INTENT_HISTORY,
        re.compile(
            r"\b(history|historical|over the (last|past)|price (chart|trend|history)|"
            rf"ohlc|candles?|last (?:\d+|{SPELLED_NUMBER_PATTERN}) (day|days|week|weeks|month|months|year|years))\b",
            re.I,
        ),
    ),
    (
        INTENT_FUNDAMENTALS,
        re.compile(
            r"\b(fundamentals?|revenue|earnings|eps|ebitda|market cap|"
            r"market capitalisation|market capitalization|p/e|pe ratio|profit margin|"
            r"dividend yield|return on equity|balance sheet|income statement|cash flow)\b",
            re.I,
        ),
    ),
    (
        INTENT_QUOTE,
        re.compile(
            r"\b(share price|stock price|current price|latest price|quote|trading at|"
            r"how much (is|are).*(share|stock)|price of)\b",
            re.I,
        ),
    ),
    (
        INTENT_PROFILE,
        re.compile(r"\b(company profile|about the company|which exchange|listed on|sector|industry)\b", re.I),
    ),
    (
        INTENT_LOOKUP,
        re.compile(r"\b(find (the )?(uk )?company|look ?up (the )?company|company number|registered (company|number))\b", re.I),
    ),
]

# A market intent alone is not enough — "revenue" also appears in ordinary
# accounting questions ("how is revenue recognised?"). A company must be named
# too, which the service checks via identity resolution. These patterns
# short-circuit the obvious educational phrasings before that even runs.
_EDUCATIONAL = re.compile(
    r"\b(how (is|are|do|does)|what is|what are|define|explain|meaning of|difference between|"
    r"under (ifrs|gaap|ias|asc)|recognit?ion|principle|standard|treatment|journal entr)\b",
    re.I,
)


def detect_intent(query: str) -> Optional[str]:
    """The market-data intent of a question, or None when it has none.

    Returns None for educational questions even when they contain a metric
    word, so "how is revenue recognised under IFRS 15?" stays with the normal
    web-grounded path instead of trying to look up a company's revenue.
    """
    if _EDUCATIONAL.search(query):
        # "Apple's revenue" is a lookup; "how is revenue recognised" is not.
        # Only bail out when the educational phrasing is not paired with an
        # explicit filings/quote request.
        if not re.search(r"\b(filing|filings|share price|stock price|quote|market cap)\b", query, re.I):
            return None
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(query):
            return intent
    return None


# ── Providers ────────────────────────────────────────────────────────────────

# \d{1,3} OR a spelled-out number ("the last twenty days") in the count
# group — see number_words.py's docstring for why this needed a shared fix.
_SPAN = re.compile(rf"\b(?:last|past)\s+(\d{{1,3}}|{SPELLED_NUMBER_PATTERN})\s*(day|week|month|year)s?\b", re.I)
_SPAN_MULTIPLIER = {"day": 1, "week": 5, "month": 21, "year": 252}  # trading days


def requested_bars(query: str, default: int = 30) -> int:
    """How many bars a question is asking for.

    "the last 30 days" means 30 calendar days, which is about 21 trading bars —
    but over-fetching slightly and showing the caller everything is better than
    silently truncating a month to ten points, which is what a fixed default
    did. Capped so a stray "last 999 years" cannot ask a provider for a decade.
    """
    match = _SPAN.search(query)
    if not match:
        return default
    raw_count = match.group(1)
    count = int(raw_count) if raw_count.isdigit() else find_first_spelled_number(raw_count)
    if count is None:
        return default
    return max(1, min(count * _SPAN_MULTIPLIER.get(match.group(2).lower(), 1), 400))


def all_providers() -> list[BaseStockProvider]:
    return [TwelveDataProvider()]


_DEFAULT_PRIORITY: dict[str, tuple[str, ...]] = {
    INTENT_QUOTE: ("twelve_data",),
    INTENT_HISTORY: ("twelve_data",),
    INTENT_FUNDAMENTALS: ("twelve_data",),
    INTENT_PROFILE: ("twelve_data",),
    # Filings are UK/US statutory records a market-price API does not carry, so
    # this intent has no provider — providers_for() returns [] and the connector
    # stays silent, falling back to the normal web-grounded answer.
    INTENT_FILINGS: (),
    INTENT_LOOKUP: ("twelve_data",),
}


def _priority_override(intent: str) -> Optional[tuple[str, ...]]:
    """Per-intent override, e.g. MARKET_DATA_PRIORITY_STOCK_QUOTE=polygon,finnhub.
    Selection stays configurable without editing business logic (plan §7)."""
    raw = os.getenv(f"MARKET_DATA_PRIORITY_{intent.upper()}", "").strip()
    if not raw:
        return None
    names = tuple(n.strip() for n in raw.split(",") if n.strip())
    return names or None


def providers_for(intent: str) -> list[BaseStockProvider]:
    """Configured providers that can serve `intent`, in priority order.

    Filters on three things, in this order: the provider declares the
    capability, an operator has configured a key, and the priority table lists
    it. A provider missing any of the three is skipped silently — an
    unconfigured provider is a normal state, not an error.
    """
    capability = INTENT_CAPABILITY.get(intent)
    if capability is None:
        return []

    order = _priority_override(intent) or _DEFAULT_PRIORITY.get(intent, ())
    by_name = {p.name: p for p in all_providers()}

    selected: list[BaseStockProvider] = []
    for name in order:
        provider = by_name.get(name)
        if provider is None or not provider.supports(capability) or not provider.configured():
            continue
        selected.append(provider)
    return selected


def any_configured() -> bool:
    return any(p.configured() for p in all_providers())
