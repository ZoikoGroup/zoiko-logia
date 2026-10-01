"""Resolving which company a question is about.

One entity carries different keys in different systems: Barclays is company
number 01026167 at Companies House, ticker BCS on NYSE and BARC.L in London.
Nothing downstream can combine filings with market data unless something maps
between them, so that mapping lives here rather than being re-guessed inside
each adapter.

What this module does locally (no network): pull an explicit ticker or UK
company number straight out of the question. What it deliberately does NOT do:
guess a ticker from a company name. "Apple" → AAPL is a lookup, not a rule, and
providers expose search endpoints for exactly that — see
service.py's resolution step, which falls back to a provider search when no
identifier is stated outright.

The uppercase-ticker guard is the same one app/orchestration/sec_edgar.py
arrived at the hard way: without it, "US GAAP", "VAT" and "EPS" all resolve to
real listed companies and a generic accounting question gets a stranger's
figures attached as provenance.
"""
from __future__ import annotations

import re

from app.domains.market_data.schemas import EntityRef

# ── Market indices ───────────────────────────────────────────────────────────
# An index is not a company, so it has no ticker in the sense above and no
# EntityRef name a provider can search for. It does have a well-known provider
# symbol, though, and that symbol is the only thing standing between "what is
# the S&P 500?" and a web search. Each entry is keyed by a regex over how the
# index is actually written in a question — "S&P 500", "S&P500", "SP500",
# "the 500" all appear — and the value is (provider symbol, display name,
# country).
#
# The provider symbol is Yahoo/Alpha-Vantage style, which is the convention both
# Finnhub and Alpha Vantage quote indices under, so the same symbol works for
# both. Verified live: ^GSPC, ^FTSE, ^GSPTSE, ^AXJO and ^ISEQ all return data.
_INDEX_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (re.compile(r"\bs\s*&\s*p\s*-?\s*500\b|\bsp\s?x?500\b", re.I), "^GSPC", "S&P 500", "US"),
    (re.compile(r"\bftse\s*100\b|\bfootsie\b", re.I), "^FTSE", "FTSE 100", "GB"),
    (re.compile(r"\btsx\s*(?:composite|60)?\b", re.I), "^GSPTSE", "TSX Composite", "CA"),
    (re.compile(r"\basx\s*200\b", re.I), "^AXJO", "S&P/ASX 200", "AU"),
    (re.compile(r"\biseq\b", re.I), "^ISEQ", "ISEQ All Shares", "IE"),
    (re.compile(r"\bdax\b", re.I), "^GDAXI", "DAX", "DE"),
    (re.compile(r"\beuronext\s*100\b", re.I), "^N100", "Euronext 100", "FR"),
    (re.compile(r"\bnikkei\s*225\b", re.I), "^N225", "Nikkei 225", "JP"),
    (re.compile(r"\bnifty(?:\s*50)?\b|\bnse\s+(?:nifty|50)\b", re.I), "^NSEI", "NIFTY 50", "IN"),
    (re.compile(r"\bsensex\b|\bbse\s+sensex\b", re.I), "^BSESN", "S&P BSE SENSEX", "IN"),
    (re.compile(r"\bsse\s*(?:composite|index)\b|\bshanghai\s*(?:composite|index)\b", re.I), "000001.SS", "SSE Composite", "CN"),
    (re.compile(r"\bhang\s*seng\b", re.I), "^HSI", "Hang Seng", "HK"),
    (re.compile(r"\bcac\s*40\b", re.I), "^FCHI", "CAC 40", "FR"),
    (re.compile(r"\bibex\s*35\b", re.I), "^IBEX", "IBEX 35", "ES"),
    (re.compile(r"\bdow\s+jones\b", re.I), "^DJI", "Dow Jones Industrial Average", "US"),
    (re.compile(r"\bnasdaq\s*(?:100|composite)?\b", re.I), "^IXIC", "NASDAQ Composite", "US"),
    (re.compile(r"\bsmi\b", re.I), "^SSMI", "Swiss Market Index", "CH"),
    (re.compile(r"\bbel\s*20\b", re.I), "^BFX", "BEL 20", "BE"),
)


# Exchange suffixes that are NOT valid standalone tickers. These appear after a dot
# in local listings (7203.T, RELIANCE.NS) but would be incorrectly matched as
# tickers on their own if the base part is too long or not recognised.
_EXCHANGE_SUFFIXES = frozenset({
    "T", "DE", "F", "PA", "IR", "NS", "BO", "HK", "SS", "SZ", "AX", "L",
    "SI", "JK", "KL", "TA", "IS", "SA", "DU", "ST", "HM", "HA", "SG",
    "WA", "GV", "MC", "VI", "PR", "MX", "ME", "CO", "AT", "AS", "BR",
    "LS", "MI", "SW", "TO", "VI", "HE", "CO", "OL", "IC",
})


def has_foreign_exchange_suffix(ticker: str) -> bool:
    """Whether a ticker carries a non-US exchange suffix (7203.T, SIE.DE).

    A dotted symbol with a known foreign exchange code cannot be a US listing,
    so a provider whose coverage is US-only should step aside rather than
    answer. This matters because of what the service does with the answer:
    ProviderBadResponse STOPS the chain, on the reasoning that a provider
    answering "nothing here" is information. But for a foreign symbol that
    answer is really "I do not cover this exchange", which is the case the
    chain is supposed to fall through — verified live, where Polygon's failure
    on 7203.T ended the search before the keyless adapter that does serve it
    was ever reached.

    US ADRs carry no suffix (SAP, TTE, BABA), so this correctly says False for
    them: those are US-listed and the US providers should answer.
    """
    text = (ticker or "").strip()
    if "." not in text:
        return False
    suffix = text.rsplit(".", 1)[-1].upper()
    return suffix in _EXCHANGE_SUFFIXES


def resolve_index(query: str) -> tuple[str, str, str] | None:
    """(provider symbol, display name, country) for a named index, or None.

    A deliberately small closed set. An index not listed here returns no match
    rather than a guessed symbol: handing a provider a symbol we guessed would
    return some OTHER index's level, and a market benchmark quoted at the wrong
    level is a serious error, not a near-miss.
    """
    for pattern, symbol, name, country in _INDEX_PATTERNS:
        if pattern.search(query or ""):
            return symbol, name, country
    return None


# Companies House numbers are 8 characters: 8 digits (England/Wales), or a
# 2-letter prefix plus 6 digits (SC… Scotland, NI… Northern Ireland, OC/LP…
# partnerships, FC… overseas).
_COMPANY_NUMBER = re.compile(r"\b((?:[A-Z]{2}\d{6})|(?:\d{8}))\b")

# Ticker-shaped tokens, optionally with an exchange suffix (BARC.L, RY.TO, 7203.T).
# The base may be letters or digits (e.g., 7203.T, 600519.SS, 0700.HK, RELIANCE.NS).
# Some exchanges use up to 6 digits (Shanghai) or longer alphabetic codes (NSE
# tickers like RELIANCE, TATAMOTORS can be 8-10 chars), so allow up to 12.
_TICKER_TOKEN = re.compile(r"\b([A-Z0-9]{1,12}(?:\.[A-Z]{1,3})?)\b")

# Uppercase words that are jargon, not tickers. Every one of these is a real
# listed symbol somewhere, which is precisely why the list is needed.
_TICKER_STOPWORDS = {
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS", "IT",
    "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP", "US", "UK", "WE", "ALL",
    "AND", "ANY", "ARE", "CAN", "FOR", "HAS", "HOW", "NEW", "NOT", "NOW", "ONE",
    "OUT", "THE", "WAS", "WHO", "WHY", "YOU", "CEO", "CFO", "EPS", "GDP", "SEC",
    "USA", "VAT", "GST", "TAX", "ROI", "ROE", "IPO", "ETF", "GAAP", "IFRS",
    "EBIT", "FY", "Q1", "Q2", "Q3", "Q4", "K", "Q", "PLC", "LTD", "INC", "LLC",
    "OHLC", "NYSE", "LSE", "API", "PDF", "CSV", "HTTP", "JSON", "AI", "ML",
}

# Names common enough to be worth resolving without a network round-trip. This
# is a convenience shortcut, not a registry — anything absent goes to a provider
# search, which is the authoritative path.
#
# Every ticker below was confirmed by a live provider lookup that returned this
# company under that symbol with that name, not inferred from the company's home
# exchange. Where a US-listed line exists it is preferred even for a non-US
# company (Toyota is TM, not 7203.T), for one reason: Finnhub serves
# fundamentals for the US line and 403s the local listing, so the ADR is the
# only symbol that can answer both "Toyota share price" and "Toyota revenue".
# Splitting the two across different listings would put a yen price and a
# dollar fundamental in the same answer.
#
# The country recorded is the company's home country, not the listing venue —
# the same convention as barclays below, which is BCS on the NYSE.
_WELL_KNOWN: dict[str, tuple[str, str]] = {
    "apple": ("AAPL", "US"),
    "microsoft": ("MSFT", "US"),
    "alphabet": ("GOOGL", "US"),
    "google": ("GOOGL", "US"),
    "amazon": ("AMZN", "US"),
    "tesla": ("TSLA", "US"),
    "nvidia": ("NVDA", "US"),
    "meta": ("META", "US"),
    "netflix": ("NFLX", "US"),
    "barclays": ("BCS", "GB"),
    "hsbc": ("HSBC", "GB"),
    "vodafone": ("VOD", "GB"),
    "shell": ("SHEL", "GB"),
    "unilever": ("UL", "GB"),
    "rolls-royce": ("RYCEY", "GB"),
    "rolls royce": ("RYCEY", "GB"),
    # The large-caps of the other nine, all confirmed by provider lookup. These
    # are the names that used to resolve wrongly or not at all: a bare uppercase
    # "LVMH" is a ticker-shaped string that pointed at a different company
    # entirely, and "Toyota" or "Reliance Industries" resolved to nothing.
    "sap": ("SAP", "DE"),
    "siemens": ("SIEGY", "DE"),
    "lvmh": ("LVMUY", "FR"),
    "totalenergies": ("TTE", "FR"),
    "toyota": ("TM", "JP"),
    "sony": ("SONY", "JP"),
    "alibaba": ("BABA", "CN"),
    "tencent": ("TCEHY", "CN"),
    "infosys": ("INFY", "IN"),
    # No verified US line for these three, so the local listing is recorded.
    # "reliance industries" is deliberately absent of any RIL/RLI guess: RLI is
    # a different company entirely (Ralph Lauren/RLI Corp) and RIL returns
    # nothing from any provider checked.
    "reliance industries": ("RELIANCE.NS", "IN"),
    "ryanair": ("RYA.IR", "IE"),
    "crh": ("CRH", "IE"),
    "shopify": ("SHOP", "CA"),
    "royal bank of canada": ("RY", "CA"),
    "bhp": ("BHP", "AU"),
}

# Authoritative listed-parent identifiers for ownership/filing lookups. These
# prevent a brand query from landing on a similarly named operating company,
# corporate-director vehicle, or other subsidiary in Companies House search.
_WELL_KNOWN_UK_PARENTS: dict[str, tuple[str, str]] = {
    "marks and spencer": ("MARKS AND SPENCER GROUP P.L.C.", "04256886"),
    "marks & spencer": ("MARKS AND SPENCER GROUP P.L.C.", "04256886"),
    "m&s": ("MARKS AND SPENCER GROUP P.L.C.", "04256886"),
    "sainsbury's": ("J SAINSBURY PLC", "00185647"),
    "sainsburys": ("J SAINSBURY PLC", "00185647"),
    "sainsbury": ("J SAINSBURY PLC", "00185647"),
}


def find_company_number(query: str) -> str:
    """An explicitly stated UK company number, or ""."""
    match = _COMPANY_NUMBER.search(query.upper())
    return match.group(1) if match else ""


def find_ticker(query: str) -> str:
    """A ticker stated outright in the question, or "".

    Requires the token to be uppercase in the ORIGINAL text: lowercase "it" and
    "us" are ordinary words, uppercase "IT" and "US" are still usually jargon
    (hence the stopword list), but a genuine ticker is virtually always written
    in caps.
    """
    for token in _TICKER_TOKEN.findall(query):
        if token in _TICKER_STOPWORDS:
            continue
        # A bare exchange suffix (NS, HK, DE, etc.) is not a ticker.
        if token in _EXCHANGE_SUFFIXES:
            continue
        # A single letter is a valid ticker (F = Ford) but far more often a
        # stray initial, so require it to be preceded by a $ or followed by a
        # market word to count.
        if len(token) == 1 and not re.search(rf"\${token}\b|\b{token}\s+(stock|share|ticker)", query):
            continue
        return token
    return ""


def known_ticker_for_name(query: str) -> tuple[str, str, str]:
    """(ticker, country, matched_name) for a well-known name in the question.

    matched_name is a confirmed name — it came from this table, not from
    guessing at the question's wording — so it is safe to display.
    """
    lowered = f" {query.lower()} "
    best = ("", "", "")
    best_len = 0
    for name, (ticker, country) in _WELL_KNOWN.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?:['’]s)?(?![a-z0-9])", lowered) and len(name) > best_len:
            best, best_len = (ticker, country, name.title()), len(name)
    return best


def find_all_known_names(query: str) -> list[tuple[str, str, str]]:
    """Every well-known company named in the question, as (ticker, country,
    matched_name), in the order first mentioned, one entry per distinct
    ticker.

    known_ticker_for_name() deliberately keeps only its single best (longest)
    match, which is right for pinning a query to one company — but a
    comparison question ("Compare Apple and Microsoft...") names more than
    one on purpose, and that best-match logic would silently discard every
    company but one before the caller ever sees them. "amazon" and
    "alphabet"/"google" resolve to distinct tickers; "shell" would also match
    inside a longer alias if one existed, which is why matches are still
    ranked longest-first per position rather than taken in dict order.
    """
    lowered = f" {query.lower()} "
    matches: list[tuple[int, str, str, str]] = []  # (position, ticker, country, name)
    for name, (ticker, country) in _WELL_KNOWN.items():
        match = re.search(rf"(?<![a-z0-9]){re.escape(name)}(?:['’]s)?(?![a-z0-9])", lowered)
        if match:
            matches.append((match.start(), ticker, country, name.title()))
    matches.sort()
    seen_tickers: set[str] = set()
    ordered: list[tuple[str, str, str]] = []
    for _, ticker, country, name in matches:
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        ordered.append((ticker, country, name))
    return ordered


def resolve_local(query: str) -> EntityRef:
    """Best-effort resolution using only the text of the question.

    Returns an EntityRef that may be empty — `has_any_id()` is false when the
    question named no company we could pin down, and the caller should either
    run a provider search or decline rather than guess.

    The well-known-name table is consulted BEFORE the uppercase-token scan, and
    the order is load-bearing. Both are how a company gets pinned, they can
    disagree, and the token scan is the one that guesses: "LVMH share price"
    contains "LVMH" in caps, which reads as a ticker and resolved to a company
    that is not LVMH, while the name table knows what the question meant. A
    confirmed name always wins. Verified live: the ordering fixed LVMH, SAP,
    Siemens, BHP and Sony, whose bare uppercase forms all resolved to
    something other than the company asked about.
    """
    company_number = find_company_number(query)
    country = "GB" if company_number else ""

    lowered = query.casefold()
    for alias in sorted(_WELL_KNOWN_UK_PARENTS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered):
            parent_name, parent_number = _WELL_KNOWN_UK_PARENTS[alias]
            return EntityRef(name=parent_name, company_number=parent_number, country="GB")

    known_ticker, known_country, name = known_ticker_for_name(query)
    if known_ticker:
        return EntityRef(
            ticker=known_ticker, company_number=company_number,
            country=country or known_country, name=name,
        )

    return EntityRef(
        ticker=find_ticker(query), company_number=company_number, country=country
    )


def company_name_hint(query: str) -> str:
    """The most likely company-name phrase to hand to a provider's SEARCH
    endpoint: the question with interrogative scaffolding and metric words
    stripped, so "Show me Rolls-Royce filings" searches for "Rolls-Royce".

    A search term, never a display name — it is a best-effort phrase, and
    showing it to a reader as though it were the company's name produces
    things like "Apple s". Only a name confirmed by a provider (or by the
    well-known table) is fit to display.
    """
    # Possessives first: stripping punctuation before the "'s" leaves a
    # stranded "s" that then reads as part of the name.
    query = re.sub(r"['’]s\b", "", query)
    cleaned = re.sub(
        r"\b(show|me|find|get|what|whats|what's|is|are|the|of|for|a|an|latest|current|"
        r"give|list|please|about|tell|price|quote|share|shares|stock|stocks|filing|filings|"
        r"revenue|profit|earnings|history|historical|chart|company|companies|plc|ltd|limited|"
        r"inc|corp|uk|us|please)\b",
        " ",
        query,
        flags=re.I,
    )
    cleaned = re.sub(r"[^\w\s&.\-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
