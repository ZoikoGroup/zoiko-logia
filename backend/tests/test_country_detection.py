"""countries_in_query must apply the capitals-only rule for bare ISO codes,
as _country_in_query already does: the pronoun/preposition "in" and "us"
are words, "IN" and "US" are countries."""
import pytest

from app.orchestration.dbnomics import _country_in_query, countries_in_query


@pytest.mark.parametrize("query", [
    "Explain IFRS 16 lease accounting in brief.",
    "What VAT rate applies to installing mobility aids in the home?",
    "Can you tell us the VAT registration threshold?",
    "Now show it in a bar chart.",
])
def test_ordinary_words_are_not_countries(query):
    # Reported: every question containing "in" was read as naming India, which
    # disabled follow-up chart reuse and would have pointed UK VAT questions at
    # Indian GST sources.
    assert countries_in_query(query) == []


@pytest.mark.parametrize("query, expected", [
    ("IN GDP growth rate", ["India"]),
    ("US inflation last 5 years", ["United States"]),
    ("Compare inflation in India and the UK", ["India", "United Kingdom"]),
    ("What is the GST rate in Australia?", ["Australia"]),
    ("What is the VAT rate in the UAE?", []),  # not a supported country, and not India
])
def test_countries_and_capital_iso_codes_are_detected(query, expected):
    assert countries_in_query(query) == expected


def test_both_detectors_agree_on_the_first_country():
    for query in ["IN GDP growth", "inflation in Japan", "tell us about Canada", "explain accruals in brief"]:
        found = countries_in_query(query)
        assert (found[0] if found else None) == _country_in_query(query)
