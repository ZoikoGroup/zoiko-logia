"""Regression tests: the bundle's reported jurisdiction must follow the
user's selection and the query, never a hardcoded default.

Reported bug — "what is india's current GDP?" answered with the jurisdiction
chip reading "US". retrieve.py resolved the bundle jurisdiction as:

    national_us_data = category in {"economic-data", "interest-rate", "exchange-rate"}
    resolved_jurisdiction = ("US" if us_authority_present or national_us_data
                             else jurisdiction) or ...

Every GDP question classifies as economic-data, so *any* such query reported
"US" no matter which jurisdiction was selected or which country the query
named — and the label then contradicted the country whose data was actually
fetched. The second branch (a US marker in a source title) had the same
failure mode for any non-US question that retrieved a US document.

Jurisdiction is now resolved through the same classifier that picks which
country's live data to fetch, so the two cannot disagree.
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from app.core.database import AsyncSessionLocal
from app.domains.live_sources.classifier import jurisdiction_for_query
from app.orchestration.retrieve import build_source_bundle, infer_category


def test_the_gdp_queries_that_reported_us_now_report_india():
    """The exact reported queries. Both classify as economic-data, which is
    what used to force "US"."""
    for query in ("what is india's current GDP?", "compare past 10 years GDP growth of india"):
        assert infer_category(query) == "economic-data", "precondition: the category that used to force US"
        assert jurisdiction_for_query(query, "") == "India"


def test_an_explicit_selection_is_honoured():
    """A selected jurisdiction governs retrieval filtering and the live-data
    country, so the reported jurisdiction must agree with it rather than with
    a country mentioned in passing."""
    assert jurisdiction_for_query("what is india's current GDP?", "US") == "US"
    assert jurisdiction_for_query("what is the GDP?", "India") == "India"
    assert jurisdiction_for_query("what is the unemployment rate?", "UK") == "UK"


def test_the_country_named_in_the_query_is_used_when_nothing_is_selected():
    assert jurisdiction_for_query("what is the US GDP?", "") == "US"
    assert jurisdiction_for_query("what is the UK unemployment rate?", "") == "UK"
    assert jurisdiction_for_query("how many people are out of work in Britain?", "") == "UK"


def test_no_country_resolves_to_empty_rather_than_a_guess():
    """A question with no country must not be labelled with one — "" renders
    as "Any jurisdiction". Returning a default here is the original bug."""
    assert jurisdiction_for_query("what is materiality in auditing?", "") == ""
    assert jurisdiction_for_query("explain double-entry bookkeeping", "") == ""


def test_framework_and_region_selections_do_not_invent_a_country():
    """"IFRS"/"UAE" are frameworks/regions with no live-data country. They
    must not silently resolve to some other country's data — the same class
    of bug as the UAE/Bank-Rate incident documented in classifier.py."""
    assert jurisdiction_for_query("what is the inflation rate?", "IFRS") == ""
    assert jurisdiction_for_query("what is the inflation rate?", "UAE") == ""


def test_canonical_tokens_match_the_application_vocabulary():
    """The bundle reports the dropdown / sources.jurisdiction_scope spelling
    ("UK"), not the human display label ("United Kingdom") — otherwise the
    chip disagrees with the selector for the very same jurisdiction."""
    assert jurisdiction_for_query("UK inflation", "") == "UK"
    assert jurisdiction_for_query("United Kingdom inflation", "") == "UK"
    assert jurisdiction_for_query("United States GDP", "") == "US"


@pytest.mark.network
async def test_bundle_reports_india_for_an_india_query_live():
    """End-to-end against the real source registry: the bundle a caller
    actually receives carries the corrected jurisdiction."""
    async with AsyncSessionLocal() as db:
        bundle = await build_source_bundle(
            db,
            query="what is india's current GDP?",
            jurisdiction="",
            tenant_id="GLOBAL_CONTROL",
            raw_chunks=[],  # isolate from vector search
        )
        assert bundle.jurisdiction == "India", (
            f"expected the bundle to follow the query's country, got {bundle.jurisdiction!r}"
        )
    print("test_bundle_reports_india_for_an_india_query_live: PASSED")


if __name__ == "__main__":
    test_the_gdp_queries_that_reported_us_now_report_india()
    test_an_explicit_selection_is_honoured()
    test_the_country_named_in_the_query_is_used_when_nothing_is_selected()
    test_no_country_resolves_to_empty_rather_than_a_guess()
    test_framework_and_region_selections_do_not_invent_a_country()
    test_canonical_tokens_match_the_application_vocabulary()
    print("All tests passed successfully!")
