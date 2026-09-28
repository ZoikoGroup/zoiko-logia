"""Company names -> tickers via the SEC registrant index.

market_data/identity.py deliberately refuses to guess a ticker from a company
name and keeps a hand-written table of sixteen well-known ones, so "nike stock
price" resolved to nothing locally. sec_edgar.py already downloads
company_tickers.json — roughly ten thousand US registrants — for a different
purpose; these tests pin the wiring that lets market data use it, and the
guard that stops it matching ordinary prose.
"""
from __future__ import annotations

import pytest

from app.domains.market_data.identity import company_name_hint
from app.orchestration.sec_edgar import _registrant_by_exact_name, resolve_company

# A stand-in for company_tickers.json. "TARGET CORP" is here on purpose: it is
# the registrant that made the prose guard necessary in the first place.
REGISTRANTS = [
    {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    {"cik_str": 320187, "ticker": "NKE", "title": "NIKE, Inc."},
    {"cik_str": 829224, "ticker": "SBUX", "title": "STARBUCKS CORP"},
    {"cik_str": 27419, "ticker": "TGT", "title": "TARGET CORP"},
    {"cik_str": 77476, "ticker": "PEP", "title": "PEPSICO INC"},
    {"cik_str": 1467373, "ticker": "ACN", "title": "Accenture plc"},
    # Two filers normalising to the same short name — ambiguity must not be
    # resolved by list order.
    {"cik_str": 111111, "ticker": "SNDA", "title": "Sound Group Inc."},
    {"cik_str": 222222, "ticker": "SNDB", "title": "Sound Group"},
]


@pytest.mark.parametrize(
    "query, expected_ticker",
    [
        ("current nike stock price", "NKE"),
        ("starbucks stock price", "SBUX"),
        ("current pepsico stock price", "PEP"),
        ("accenture share price", "ACN"),
    ],
)
def test_a_lower_case_company_name_resolves_through_the_hint(query, expected_ticker):
    """The hint is the query with its scaffolding removed, so it IS the name.

    resolve_company() will not match a bare lower-case word mid-sentence, and
    that guard stays. Matching the stripped hint instead reaches the same
    answer without weakening it.
    """
    assert resolve_company(query, REGISTRANTS) is None
    entry = _registrant_by_exact_name(company_name_hint(query), REGISTRANTS)
    assert entry is not None and entry["ticker"] == expected_ticker


def test_prose_that_merely_contains_a_company_word_resolves_to_nothing():
    """The regression this whole approach exists to avoid.

    Dropping the capitalisation guard resolved "set a target revenue for next
    year" to TARGET CORP — a real company's figures attached as provenance to
    a question that was never about it. The hint for that sentence is not a
    company name, so nothing matches.
    """
    query = "set a target revenue for next year"
    assert resolve_company(query, REGISTRANTS) is None
    assert _registrant_by_exact_name(company_name_hint(query), REGISTRANTS) is None


@pytest.mark.parametrize(
    "query",
    [
        "what is market cap",
        "how do i calculate market cap",
        "explain share price movements",
        "how to read an income statement",
        "explain sound revenue recognition",
    ],
)
def test_ordinary_questions_never_resolve_to_a_registrant(query):
    assert _registrant_by_exact_name(company_name_hint(query), REGISTRANTS) is None


def test_an_ambiguous_name_is_refused_rather_than_guessed():
    """Two filers share the normalised name "sound group"; picking either by
    list order is how one company's figures end up on another's answer."""
    assert _registrant_by_exact_name("Sound Group", REGISTRANTS) is None


def test_very_short_names_are_refused():
    """Names under four characters collide with ordinary prose constantly;
    they stay reachable through their ticker instead."""
    assert _registrant_by_exact_name("HP", REGISTRANTS) is None
    assert _registrant_by_exact_name("", REGISTRANTS) is None


def test_a_capitalised_name_still_goes_through_the_strict_path():
    """The hint route is an addition, not a replacement — the existing
    behaviour for well-formed references is untouched."""
    entry = resolve_company("What was Apple's revenue in 2023?", REGISTRANTS)
    assert entry is not None and entry["ticker"] == "AAPL"
