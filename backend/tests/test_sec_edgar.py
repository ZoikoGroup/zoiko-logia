import os
import sys

# Ensure backend root is in search path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.orchestration.sec_edgar import (
    filing_index_url,
    find_year,
    format_value,
    latest_annual_fact,
    normalise_company_name,
    pick_concepts,
    resolve_company,
)

# A stand-in for company_tickers.json, in the same shape EDGAR serves.
_REGISTRANTS = [
    {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."},
    {"cik_str": 37996, "ticker": "F", "title": "Ford Motor Co"},
    {"cik_str": 39911, "ticker": "GPS", "title": "Gap, Inc."},
    # Registrants whose names are ordinary words — the false-positive class.
    # "Target Group" is listed before "TARGET CORP" on purpose: both normalise
    # to "target", so list order would decide the winner without a tiebreak.
    {"cik_str": 1443089, "ticker": "CBDY", "title": "Target Group Inc."},
    {"cik_str": 27419, "ticker": "TGT", "title": "TARGET CORP"},
    {"cik_str": 1420720, "ticker": "SOGP", "title": "Sound Group Inc."},
]


def test_company_name_normalisation_strips_corporate_suffixes():
    assert normalise_company_name("Apple Inc.") == "apple"
    assert normalise_company_name("MICROSOFT CORP") == "microsoft"
    assert normalise_company_name("Tesla, Inc.") == "tesla"
    assert normalise_company_name("Ford Motor Co") == "ford motor"
    print("test_company_name_normalisation_strips_corporate_suffixes: PASSED")


def test_resolves_company_by_name():
    entry = resolve_company("What was Apple's revenue last year?", _REGISTRANTS)
    assert entry is not None and entry["ticker"] == "AAPL"
    print("test_resolves_company_by_name: PASSED")


def test_resolves_company_by_ticker_when_no_name_present():
    entry = resolve_company("Show me MSFT total assets", _REGISTRANTS)
    assert entry is not None and entry["ticker"] == "MSFT"
    print("test_resolves_company_by_ticker_when_no_name_present: PASSED")


def test_longest_name_match_wins():
    """"Ford Motor" must beat a bare "Ford" so a multi-word registrant is not
    lost to a shorter prefix match."""
    entry = resolve_company("Ford Motor net income", _REGISTRANTS)
    assert entry is not None and entry["ticker"] == "F"
    print("test_longest_name_match_wins: PASSED")


def test_ordinary_words_do_not_resolve_as_tickers():
    """Uppercase jargon in a finance question must not resolve to a registrant —
    the single most likely false positive for this connector."""
    assert resolve_company("How does US GAAP treat R&D?", _REGISTRANTS) is None
    assert resolve_company("What is the VAT rate?", _REGISTRANTS) is None
    print("test_ordinary_words_do_not_resolve_as_tickers: PASSED")


def test_short_names_are_not_matched_from_prose():
    """"Gap" is a real registrant but also an ordinary word; it must not fire on
    prose. It stays reachable via its ticker."""
    assert resolve_company("Explain the expectation gap in auditing", _REGISTRANTS) is None
    entry = resolve_company("GPS revenue", _REGISTRANTS)
    assert entry is not None and entry["ticker"] == "GPS"
    print("test_short_names_are_not_matched_from_prose: PASSED")


def test_lowercase_common_word_names_do_not_hijack_generic_questions():
    """Registrants named after ordinary words are the sharpest false-positive
    edge: without a guard these attach a real company's figures as provenance
    for a question that was never about them."""
    assert resolve_company("What is a target operating income for a retailer?", _REGISTRANTS) is None
    assert resolve_company("How do I set a target revenue for next year?", _REGISTRANTS) is None
    assert resolve_company("Explain sound revenue recognition practices", _REGISTRANTS) is None
    print("test_lowercase_common_word_names_do_not_hijack_generic_questions: PASSED")


def test_capitalised_or_possessive_names_still_resolve():
    """The guard above must not cost ordinary phrasings — a capitalised name, a
    possessive, or a multi-word name are all real references."""
    assert resolve_company("Apple revenue 2023", _REGISTRANTS)["ticker"] == "AAPL"
    assert resolve_company("apple's revenue last year", _REGISTRANTS)["ticker"] == "AAPL"
    assert resolve_company("Ford Motor net income", _REGISTRANTS)["ticker"] == "F"
    print("test_capitalised_or_possessive_names_still_resolve: PASSED")


def test_same_normalised_name_resolves_to_the_titled_registrant():
    """"Target Group Inc." and "TARGET CORP" both normalise to "target", so the
    full filed title breaks the tie rather than list order."""
    assert resolve_company("Target Corp revenue", _REGISTRANTS)["ticker"] == "TGT"
    print("test_same_normalised_name_resolves_to_the_titled_registrant: PASSED")


def test_specific_concepts_win_over_generic_ones():
    """"gross profit" must not also pull in the generic revenue tags."""
    labels = [label for label, _ in pick_concepts("What was Apple's gross profit?")]
    assert labels == ["Gross profit"]

    labels = [label for label, _ in pick_concepts("Apple operating income 2023")]
    assert labels == ["Operating income"]
    print("test_specific_concepts_win_over_generic_ones: PASSED")


def test_revenue_maps_to_multiple_candidate_tags():
    """Filers differ on which tag carries revenue, so the connector must try
    several rather than assuming one."""
    concepts = pick_concepts("Tesla revenue")
    assert len(concepts) == 1
    _, tags = concepts[0]
    assert "Revenues" in tags
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in tags
    print("test_revenue_maps_to_multiple_candidate_tags: PASSED")


def test_non_financial_question_selects_no_concept():
    assert pick_concepts("What is a deferred tax liability?") == []
    assert pick_concepts("hello") == []
    print("test_non_financial_question_selects_no_concept: PASSED")


def test_concept_fan_out_is_capped():
    query = "Apple revenue, net income, total assets, EPS and R&D"
    assert len(pick_concepts(query)) <= 3
    print("test_concept_fan_out_is_capped: PASSED")


def test_find_year():
    assert find_year("Apple revenue 2023") == 2023
    assert find_year("Apple revenue") is None
    assert find_year("revenue in 1850") is None
    print("test_find_year: PASSED")


def test_latest_annual_fact_ignores_quarterly_filings():
    """A 10-Q figure quoted as "the" revenue would present a quarter as a year."""
    units = {
        "USD": [
            {"start": "2023-01-01", "end": "2023-03-31", "val": 1, "form": "10-Q", "accn": "q"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 100, "form": "10-K", "accn": "a"},
        ]
    }
    fact = latest_annual_fact(units)
    assert fact is not None and fact["val"] == 100
    print("test_latest_annual_fact_ignores_quarterly_filings: PASSED")


def test_latest_annual_fact_ignores_embedded_quarters_in_a_10k():
    """A 10-K payload also carries its quarterly periods; only the full-year
    duration may be quoted."""
    units = {
        "USD": [
            {"start": "2023-10-01", "end": "2023-12-31", "val": 25, "form": "10-K", "accn": "a"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 100, "form": "10-K", "accn": "a"},
        ]
    }
    fact = latest_annual_fact(units)
    assert fact is not None and fact["val"] == 100
    print("test_latest_annual_fact_ignores_embedded_quarters_in_a_10k: PASSED")


def test_latest_annual_fact_prefers_requested_year():
    units = {
        "USD": [
            {"start": "2022-01-01", "end": "2022-12-31", "val": 90, "fy": 2022, "form": "10-K", "accn": "a"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 100, "fy": 2023, "form": "10-K", "accn": "b"},
        ]
    }
    assert latest_annual_fact(units, year=2022)["val"] == 90
    # With no year asked for, the most recent period wins.
    assert latest_annual_fact(units)["val"] == 100
    print("test_latest_annual_fact_prefers_requested_year: PASSED")


def test_latest_annual_fact_handles_instant_facts():
    """Balance-sheet facts (Assets) have no `start` and must not be filtered out
    by the full-year duration rule."""
    units = {
        "USD": [
            {"end": "2023-09-30", "val": 352583000000, "form": "10-K", "accn": "a"},
        ]
    }
    fact = latest_annual_fact(units)
    assert fact is not None and fact["val"] == 352583000000
    print("test_latest_annual_fact_handles_instant_facts: PASSED")


def test_latest_annual_fact_returns_none_without_annual_data():
    units = {"USD": [{"start": "2023-01-01", "end": "2023-03-31", "val": 1, "form": "10-Q"}]}
    assert latest_annual_fact(units) is None
    assert latest_annual_fact({}) is None
    print("test_latest_annual_fact_returns_none_without_annual_data: PASSED")


def test_format_value_keeps_the_exact_figure():
    """The scaled reading is a convenience; the exact filed number must survive
    so the answer can be checked against the filing."""
    assert format_value(391035000000, "USD") == "$391,035,000,000 ($391.04 billion)"
    assert format_value(2500000, "USD") == "$2,500,000 ($2.50 million)"
    assert format_value(6.13, "USD/shares") == "$6.13 per share"
    print("test_format_value_keeps_the_exact_figure: PASSED")


def test_filing_index_url_points_at_the_filing():
    url = filing_index_url(320193, "0000320193-23-000106")
    assert url.endswith("/Archives/edgar/data/320193/000032019323000106/0000320193-23-000106-index.htm")
    print("test_filing_index_url_points_at_the_filing: PASSED")
