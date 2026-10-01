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

Priority rationale, not arbitrary:
  - UK filings go to Companies House alone. It is the statutory register; no
    other provider here can supply UK filing history, and none should be
    consulted as a "fallback" for it.
  - Alpha Vantage is last for every market intent. Its free tier is roughly 25
    calls per day — viable as a backstop, not as a primary.
  - Polygon leads history (deep, adjusted aggregates) but not quotes, where its
    free tier only reaches the previous close.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from app.orchestration.number_words import SPELLED_NUMBER_PATTERN, find_first_spelled_number
from app.domains.market_data.providers.alpha_vantage import AlphaVantageProvider
from app.domains.market_data.providers.base import (
    CAP_FILINGS,
    CAP_FUNDAMENTALS,
    CAP_HISTORY,
    CAP_PROFILE,
    CAP_QUOTE,
    CAP_SEARCH,
    BaseStockProvider,
)
from app.domains.market_data.providers.companies_house import CompaniesHouseProvider
from app.domains.market_data.providers.finnhub import FinnhubProvider
from app.domains.market_data.providers.index_quote import IndexQuoteProvider
from app.domains.market_data.providers.polygon import PolygonProvider
from app.domains.market_data.providers.yahoo_equity import YahooEquityProvider

# ── Intents ──────────────────────────────────────────────────────────────────
INTENT_QUOTE = "stock_quote"
INTENT_HISTORY = "stock_history"
INTENT_FUNDAMENTALS = "stock_fundamentals"
INTENT_PROFILE = "stock_company_profile"
INTENT_FILINGS = "company_filings"
INTENT_LOOKUP = "company_lookup"
INTENT_INDEX = "index_quote"

INTENT_CAPABILITY = {
    INTENT_QUOTE: CAP_QUOTE,
    INTENT_HISTORY: CAP_HISTORY,
    INTENT_FUNDAMENTALS: CAP_FUNDAMENTALS,
    INTENT_PROFILE: CAP_PROFILE,
    INTENT_FILINGS: CAP_FILINGS,
    INTENT_LOOKUP: CAP_SEARCH,
    # An index is a quote-shaped question about a market benchmark rather than
    # a company. The providers below serve it with the same quote/history
    # endpoints they use for equities, so it reuses those capabilities rather
    # than declaring new ones.
    INTENT_INDEX: CAP_QUOTE,
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
        # An index question is tested before QUOTE and before the educational
        # bail-out below, because "What is the S&P 500?" contains "what is"
        # and would otherwise be classified as a definitional question and
        # sent to the web rather than to a quote provider — which is why every
        # index question in the live audit returned nothing at all.
        #
        # "index" alone is too broad to anchor on (it also means a price index
        # or a database index), so the pattern requires either one of the
        # recognised benchmark names or the word index next to a market word.
        INTENT_INDEX,
        re.compile(
            r"\b(?:s\s*&\s*p\s*500|sp\s?x?500|sp500|ftse\s*100|footsie|"
            r"tsx\s*(?:composite|60)|asx\s*200|iseq|euronext|dax|nikkei|"
            r"nifty|sensex|shanghai|sse\s*(?:composite|index)|bombay|"
            r"hang\s*seng|smi|ibex|randstad|bel\s*20|stoxx\s*600|"
            r"(?:s\s*&\s*p|dow\s+jones|nasdaq)\s*[\w-]*|cac\s*40|msci\s*\w*)\b"
            r"|\b(?:index|indices)\b(?=[^.?]*\b(?:level|value|point|performance|"
            r"today|close|chart|history|year|since|at)\b)"
            r"|\b(?:level|value|performance)\s+of\s+the\s+\w+\s+index\b",
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

# Macro-statistical words that collide with stock-fundamentals vocabulary.
# "US government revenue" is a treasury aggregate, not a question about a
# company whose name coincidentally matches — but FUNDAMENTALS fires on the
# bare word "revenue", and the provider search then resolves "government
# revenue" to some company and attaches its fundamentals as provenance. When
# the question names one of the supported countries AND a macro metric, it is
# a statistical question and belongs to the web-grounded path unless a
# specific company is also named.
_MACRO_METRIC = re.compile(
    r"\b(?:gdp|gross domestic product|inflation|cpi|consumer price(?: index)?|hicp|"
    r"unemployment|jobless|deficit|surplus|revenue|receipts|government debt|national debt|"
    r"tax(?:ation|es| revenue)?|trade (?:balance|deficit|surplus)|current account|retail sales)\b",
    re.I,
)


def detect_intent(query: str) -> Optional[str]:
    """The market-data intent of a question, or None when it has none.

    Returns None for educational questions even when they contain a metric
    word, so "how is revenue recognised under IFRS 15?" stays with the normal
    web-grounded path instead of trying to look up a company's revenue.

    An index question is resolved BEFORE the educational check, deliberately.
    "What is the S&P 500?" is a question about the value of a benchmark, and
    the educational rule would otherwise read the "what is" and decline to
    route it — which is precisely the confirmed bug where all five indices
    returned no data. The distinction that matters is whether an index is
    NAMED: "what is an index" stays educational, "what is the S&P 500" does
    not.
    """
    for intent, pattern in _INTENT_PATTERNS:
        if intent == INTENT_INDEX and pattern.search(query):
            return INTENT_INDEX
    if _EDUCATIONAL.search(query):
        # "Apple's revenue" is a lookup; "how is revenue recognised" is not.
        # Only bail out when the educational phrasing is not paired with an
        # explicit filings/quote request.
        if not re.search(r"\b(filing|filings|share price|stock price|quote|market cap)\b", query, re.I):
            return None
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(query):
            if intent in (INTENT_FUNDAMENTALS, INTENT_PROFILE, INTENT_QUOTE):
                refused = _macro_question_refusal(query)
                if refused:
                    return None
            return intent
    return None


def _macro_question_refusal(query: str) -> bool:
    """True when a query that matched a market intent is really a macro-stat
    question that market data must not answer.

    Fires on the combination the wrong-data bug needs: a supported country plus
    a macro-statistic word ("US government revenue", "Canada GDP"), no explicit
    ticker, and no well-known company name. Without the company check,
    "Apple's government revenue would be..." would be wrongly refused; with it,
    the guard only fires when there is genuinely no company to attach the
    figures to.
    """
    if not _MACRO_METRIC.search(query or ""):
        return False
    from app.orchestration.country_scope import names_country
    if not any(names_country(query or "", iso2) for iso2 in ("US", "GB", "IE", "CA", "AU", "DE", "FR", "JP", "IN", "CN")):
        return False
    from app.domains.market_data.identity import find_ticker, known_ticker_for_name
    if find_ticker(query or "") or known_ticker_for_name(query or "")[0]:
        return False
    return True


# ── Providers ────────────────────────────────────────────────────────────────

# \d{1,3} OR a spelled-out number ("the last twenty days") in the count
# group — see number_words.py's docstring for why this needed a shared fix.
_SPAN = re.compile(rf"\b(?:last|past)\s+(\d{{1,3}}|{SPELLED_NUMBER_PATTERN})\s*(day|week|month|year)s?\b", re.I)
_SPAN_MULTIPLIER = {"day": 1, "week": 5, "month": 21, "year": 252}  # trading days


_MAX_BARS = 400
_TRADING_DAYS_PER = {"week": 5, "month": 21}   # for converting a daily count


def _requested_trading_days(query: str, default: int) -> int:
    """The span in trading days, uncapped. 0 means "no span was stated"."""
    match = _SPAN.search(query)
    if not match:
        return default
    raw_count = match.group(1)
    count = int(raw_count) if raw_count.isdigit() else find_first_spelled_number(raw_count)
    if count is None:
        return default
    return max(1, count * _SPAN_MULTIPLIER.get(match.group(2).lower(), 1))


def requested_bars(query: str, default: int = 30) -> int:
    """How many DAILY bars a question is asking for.

    "the last 30 days" means 30 calendar days, which is about 21 trading bars —
    but over-fetching slightly and showing the caller everything is better than
    silently truncating a month to ten points, which is what a fixed default
    did. Capped so a stray "last 999 years" cannot ask a provider for a decade.

    Prefer requested_history_window() for history requests: this function can
    only answer in daily bars, so anything past the cap comes back truncated.
    """
    return min(_requested_trading_days(query, default), _MAX_BARS)


def requested_history_window(query: str, default: int = 30) -> tuple[str, int]:
    """(interval, bars) covering the WHOLE span the question asked for.

    Daily bars cannot express a long span: ten years is ~2,520 trading days,
    and clamping that to the 400-bar ceiling quietly returned about eighteen
    months while the answer text still said "10 years" — the truncation was
    invisible to the reader and the chart was simply wrong about its own
    period. Coarsening the interval fixes it honestly: ten years is 120
    monthly bars, comfortably inside the cap and genuinely ten years.

    Daily is kept wherever it fits, so short spans are unchanged. Providers
    already accept these interval keys (polygon.py's _INTERVAL_TO_AGG,
    alpha_vantage.py's _SERIES_FUNCTION); nothing new is requested of them.
    """
    trading_days = _requested_trading_days(query, default)
    if trading_days <= _MAX_BARS:
        return "1d", trading_days
    weeks = -(-trading_days // _TRADING_DAYS_PER["week"])      # ceil
    if weeks <= _MAX_BARS:
        return "1w", weeks
    months = -(-trading_days // _TRADING_DAYS_PER["month"])
    return "1mo", min(months, _MAX_BARS)


def all_providers() -> list[BaseStockProvider]:
    return [
        CompaniesHouseProvider(), FinnhubProvider(), PolygonProvider(),
        AlphaVantageProvider(), IndexQuoteProvider(), YahooEquityProvider(),
    ]


_DEFAULT_PRIORITY: dict[str, tuple[str, ...]] = {
    # yahoo_equity sits last among the market-data providers and before Alpha
    # Vantage, whose free tier is ~25 calls a day. The key-gated providers lead
    # because where they work they are the better source — Finnhub carries the
    # ADR fundamentals Yahoo does not — but each of them is US-shaped, and
    # verified live they fail differently: Finnhub answers a local listing with
    # 403, Polygon's failure stopped the fallback chain entirely (see
    # identity.has_foreign_exchange_suffix), and Alpha Vantage has thin
    # non-US coverage. yahoo_equity is keyless and serves all ten countries, so
    # it is what a 7203.T or 600519.SS question actually lands on.
    INTENT_QUOTE: ("finnhub", "polygon", "yahoo_equity", "alpha_vantage"),
    INTENT_HISTORY: ("polygon", "yahoo_equity", "alpha_vantage"),
    INTENT_FUNDAMENTALS: ("finnhub", "alpha_vantage"),
    INTENT_PROFILE: ("finnhub", "polygon", "alpha_vantage"),
    INTENT_FILINGS: ("companies_house",),
    INTENT_LOOKUP: ("companies_house", "finnhub", "polygon", "yahoo_equity", "alpha_vantage"),
    # The key-gated market providers cannot serve index levels — Finnhub's
    # free tier zeroes or 403s them, Alpha Vantage rejects ^-symbols, Polygon
    # has no index series — so the index path belongs to the keyless Yahoo chart
    # adapter alone. It refuses any non-^ ticker, so this entry can never leak
    # into ordinary stock quotes.
    INTENT_INDEX: ("index_quote",),
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
