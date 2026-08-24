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

# Companies House numbers are 8 characters: 8 digits (England/Wales), or a
# 2-letter prefix plus 6 digits (SC… Scotland, NI… Northern Ireland, OC/LP…
# partnerships, FC… overseas).
_COMPANY_NUMBER = re.compile(r"\b((?:[A-Z]{2}\d{6})|(?:\d{8}))\b")

# Ticker-shaped tokens, optionally with an exchange suffix (BARC.L, RY.TO).
_TICKER_TOKEN = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b")

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


def resolve_local(query: str) -> EntityRef:
    """Best-effort resolution using only the text of the question.

    Returns an EntityRef that may be empty — `has_any_id()` is false when the
    question named no company we could pin down, and the caller should either
    run a provider search or decline rather than guess.
    """
    company_number = find_company_number(query)
    ticker = find_ticker(query)
    country = "GB" if company_number else ""
    name = ""

    if not ticker:
        ticker, known_country, name = known_ticker_for_name(query)
        country = country or known_country

    return EntityRef(ticker=ticker, company_number=company_number, country=country, name=name)


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
