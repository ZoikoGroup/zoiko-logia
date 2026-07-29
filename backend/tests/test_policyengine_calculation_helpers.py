"""
Tests for the PolicyEngine-US calculation feature: the fail-closed query
parsing helpers (fast, no heavy dependency), plus one real end-to-end
calculation sanity check and a chunk-shape check (requires policyengine_us
installed — see requirements.txt).

Run locally (from backend/, venv active):
    python3 tests/test_policyengine_calculation_helpers.py
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone

from app.domains.calculation.household_extraction import (
    HouseholdParams,
    extract_annual_income,
    extract_filing_status,
    extract_num_dependents,
    extract_tax_year,
    extract_household_params,
)
from app.domains.calculation.policyengine_engine import run_calculation
from app.domains.calculation.service import to_calculation_rag_chunk, POLICYENGINE_NODE_PREFIX


# ── extract_annual_income ────────────────────────────────────────────────

def test_extract_annual_income_dollar_sign():
    assert extract_annual_income("What's my EITC if I made $32,000 this year?") == 32000.0
    print("test_extract_annual_income_dollar_sign: PASSED")


def test_extract_annual_income_keyword_anchored():
    assert extract_annual_income("What's my EITC if my income is 32000 as head of household?") == 32000.0
    print("test_extract_annual_income_keyword_anchored: PASSED")


def test_extract_annual_income_none_when_absent():
    assert extract_annual_income("What is the standard deduction for a single filer?") is None
    print("test_extract_annual_income_none_when_absent: PASSED")


def test_extract_annual_income_bare_number_not_matched():
    # A bare number with no $ sign and no income-keyword anchor is just as
    # plausibly a CFR section or a year — must not be guessed as income.
    assert extract_annual_income("What does 26 CFR 1.401 say about 2025 contributions?") is None
    print("test_extract_annual_income_bare_number_not_matched: PASSED")


def test_extract_annual_income_none_when_compound_query():
    # Real incident (2026-07-20): a two-question query silently ran the
    # second question's calculation against the FIRST figure ($45,000
    # instead of the $60,000 the second question actually asked about),
    # and the LLM then discarded the correct-for-the-wrong-figure computed
    # result and hallucinated its own number instead. More than one
    # distinct dollar figure must refuse to resolve, not guess which one.
    assert extract_annual_income(
        "What's my standard deduction if I'm single with no dependents earning "
        "$45,000 in 2025? What's my CA state income tax for $60,000 income, single, 2025?"
    ) is None
    print("test_extract_annual_income_none_when_compound_query: PASSED")


def test_extract_annual_income_same_figure_repeated_still_resolves():
    # The same dollar figure mentioned twice is not ambiguous — only
    # genuinely distinct figures should trigger the compound-query refusal.
    assert extract_annual_income(
        "For $32,000 income, what's my EITC? Assume $32,000 is all W-2 wages."
    ) == 32000.0
    print("test_extract_annual_income_same_figure_repeated_still_resolves: PASSED")


# ── extract_filing_status ────────────────────────────────────────────────

def test_extract_filing_status_head_of_household():
    assert extract_filing_status("filing as head of household") == "HEAD_OF_HOUSEHOLD"
    assert extract_filing_status("HoH with 2 kids") == "HEAD_OF_HOUSEHOLD"
    print("test_extract_filing_status_head_of_household: PASSED")


def test_extract_filing_status_married_variants():
    assert extract_filing_status("married filing jointly, $80,000 income") == "JOINT"
    assert extract_filing_status("MFJ this year") == "JOINT"
    assert extract_filing_status("married filing separately") == "SEPARATE"
    print("test_extract_filing_status_married_variants: PASSED")


def test_extract_filing_status_single():
    assert extract_filing_status("I'm single with no dependents") == "SINGLE"
    print("test_extract_filing_status_single: PASSED")


def test_extract_filing_status_none_when_absent():
    assert extract_filing_status("What's my EITC for $32,000 income?") is None
    print("test_extract_filing_status_none_when_absent: PASSED")


def test_extract_filing_status_none_when_two_distinct_statuses_named():
    # Real incident (2026-07-20): a compare-style query naming two
    # different filing statuses used to silently resolve to whichever
    # status happened to be checked first in dict iteration order,
    # regardless of which scenario the query actually described.
    assert extract_filing_status(
        "Compare take-home tax between Single vs Head of Household filers"
    ) is None
    print("test_extract_filing_status_none_when_two_distinct_statuses_named: PASSED")


def test_extract_filing_status_same_status_repeated_still_resolves():
    # Two different keyword phrasings of the *same* status ("single filer"
    # and "single") must not be treated as ambiguous.
    assert extract_filing_status("As a single filer, I'm single with no dependents") == "SINGLE"
    print("test_extract_filing_status_same_status_repeated_still_resolves: PASSED")


# ── extract_num_dependents ───────────────────────────────────────────────

def test_extract_num_dependents_explicit_number():
    assert extract_num_dependents("head of household with 2 kids") == 2
    assert extract_num_dependents("3 children, single filer") == 3
    print("test_extract_num_dependents_explicit_number: PASSED")


def test_extract_num_dependents_qualifying_children_phrasing():
    # Real incident (2026-07-20): "3 qualifying children" (the literal IRS
    # term of art for EITC/CTC dependents) returned None entirely — the
    # regex required the number immediately adjacent to "children," and
    # "qualifying" sat in between, silently blocking a perfectly legitimate,
    # non-ambiguous single-household query from ever reaching the
    # calculation engine.
    assert extract_num_dependents("3 qualifying children") == 3
    assert extract_num_dependents("two qualifying children") == 2
    print("test_extract_num_dependents_qualifying_children_phrasing: PASSED")


def test_extract_num_dependents_word_number():
    assert extract_num_dependents("head of household with two kids") == 2
    print("test_extract_num_dependents_word_number: PASSED")


def test_extract_num_dependents_zero_explicit():
    assert extract_num_dependents("single, no kids, $50,000 income") == 0
    print("test_extract_num_dependents_zero_explicit: PASSED")


def test_extract_num_dependents_defaults_to_zero_when_unmentioned():
    # No mention of dependents at all -> ordinary reading is zero, not unknown.
    assert extract_num_dependents("What's the standard deduction for a single filer earning $50,000?") == 0
    print("test_extract_num_dependents_defaults_to_zero_when_unmentioned: PASSED")


def test_extract_num_dependents_none_when_ambiguous():
    # Dependents raised as a topic, but no resolvable count -> fail closed,
    # must NOT default to 0 or guess any other number.
    assert extract_num_dependents("head of household with kids, $32,000 income") is None
    assert extract_num_dependents("how does having dependents affect my taxes?") is None
    print("test_extract_num_dependents_none_when_ambiguous: PASSED")


def test_extract_num_dependents_none_when_conflicting_counts_signaled():
    # Real incident (2026-07-20): "no dependents for the single case and 1
    # dependent for HoH" used to resolve to 0, silently discarding the "1
    # dependent" half describing a different scenario. Two distinct
    # counts signaled in one query -> ambiguous, not a guess at which one.
    assert extract_num_dependents(
        "no dependents for the single case and 1 dependent for HoH"
    ) is None
    print("test_extract_num_dependents_none_when_conflicting_counts_signaled: PASSED")


# ── extract_tax_year ──────────────────────────────────────────────────────

def test_extract_tax_year_explicit():
    assert extract_tax_year("EITC for 2025, single filer") == 2025
    print("test_extract_tax_year_explicit: PASSED")


def test_extract_tax_year_defaults_to_current_year():
    current_year = datetime.now(timezone.utc).year
    assert extract_tax_year("What's my EITC for $32,000 income, single?") == current_year
    print("test_extract_tax_year_defaults_to_current_year: PASSED")


# ── extract_household_params (the orchestration-facing gate) ────────────

def test_extract_household_params_full_query_resolves():
    params = extract_household_params(
        "What's my EITC for $32,000 income, Head of Household, 2 kids, 2025?"
    )
    assert params == HouseholdParams(
        annual_income=32000.0,
        filing_status="HEAD_OF_HOUSEHOLD",
        num_dependents=2,
        tax_year=2025,
        state_code=None,
    )
    print("test_extract_household_params_full_query_resolves: PASSED")


def test_extract_household_params_resolves_with_qualifying_children_phrasing():
    # The exact real query that surfaced this bug — a legitimate,
    # non-ambiguous single-household detailed question that used to
    # silently fail to resolve at all.
    params = extract_household_params(
        "As a Head of Household filer in 2025 with 3 qualifying children and "
        "$72,000 in W-2 wages, what's my EITC, CTC, and standard deduction?"
    )
    assert params == HouseholdParams(
        annual_income=72000.0,
        filing_status="HEAD_OF_HOUSEHOLD",
        num_dependents=3,
        tax_year=2025,
        state_code=None,
    )
    print("test_extract_household_params_resolves_with_qualifying_children_phrasing: PASSED")


def test_extract_household_params_none_when_income_missing():
    assert extract_household_params("What's my EITC as head of household with 2 kids?") is None
    print("test_extract_household_params_none_when_income_missing: PASSED")


def test_extract_household_params_none_when_filing_status_missing():
    assert extract_household_params("What's my EITC for $32,000 income with 2 kids?") is None
    print("test_extract_household_params_none_when_filing_status_missing: PASSED")


def test_extract_household_params_none_when_dependents_ambiguous():
    assert extract_household_params(
        "What's my EITC for $32,000 income, head of household, with kids?"
    ) is None
    print("test_extract_household_params_none_when_dependents_ambiguous: PASSED")


def test_extract_household_params_resolves_state():
    params = extract_household_params(
        "What's my CA state income tax for $60,000 income, single, 2025?"
    )
    assert params is not None
    assert params.state_code == "CA"
    print("test_extract_household_params_resolves_state: PASSED")


def test_extract_household_params_none_when_compound_comparison_query():
    # Real incident (2026-07-20), the exact failing query verbatim: a
    # compare-style question naming two distinct filing statuses and two
    # distinct dependent counts for two different described scenarios used
    # to silently conflate into HouseholdParams(filing_status=
    # 'HEAD_OF_HOUSEHOLD', num_dependents=0) — a household matching
    # neither described scenario ("Single, 0 dependents" or
    # "HoH, 1 dependent").
    assert extract_household_params(
        "Compare my take-home federal income tax between $70,000 income as Single "
        "vs Head of Household, 2025, no dependents for the single case and 1 "
        "dependent for HoH."
    ) is None
    print("test_extract_household_params_none_when_compound_comparison_query: PASSED")


# ── Real calculation sanity check (requires policyengine_us installed) ──
# Scenario: Head of Household, $32,000 employment income, 2 qualifying
# children, tax year 2025 — a documented PolicyEngine-US v1.775.8 output
# under current law as installed in this environment (includes the One Big
# Beautiful Bill Act's 2025 standard deduction changes). Not an IRS
# published-table figure — the point of this test is regression protection
# (the engine keeps producing this exact, previously-verified number for
# this exact scenario), not independent validation of PolicyEngine's tax
# law modeling itself.

import asyncio


def test_real_calculation_known_scenario():
    household = HouseholdParams(
        annual_income=32000.0,
        filing_status="HEAD_OF_HOUSEHOLD",
        num_dependents=2,
        tax_year=2025,
        state_code=None,
    )
    result = asyncio.run(run_calculation(household))
    assert round(result.values["eitc"], 2) == 5330.31
    assert result.values["ctc"] == 4400.0
    assert result.values["standard_deduction"] == 23625.0
    assert result.state_tax_supported is False
    print("test_real_calculation_known_scenario: PASSED")


def test_to_calculation_rag_chunk_shape():
    household = HouseholdParams(
        annual_income=32000.0,
        filing_status="HEAD_OF_HOUSEHOLD",
        num_dependents=2,
        tax_year=2025,
        state_code=None,
    )
    result = asyncio.run(run_calculation(household))
    chunk = to_calculation_rag_chunk(result, source_id="src-policyengine-us-calculation-engine")

    assert chunk["metadata"]["source_id"] == "src-policyengine-us-calculation-engine"
    assert chunk["node_id"].startswith(POLICYENGINE_NODE_PREFIX)
    assert "Head of Household" in chunk["text"]
    assert "2 dependents" in chunk["text"]
    # The exact EITC figure must appear in a form _CLAIMED_FIGURE_PATTERN
    # (massarius/answer_validator.py: r"\$\s?\d[\d,]*(?:\.\d+)?|...") will
    # actually match — this is what makes numeric-fidelity checking work
    # with zero special-casing downstream.
    assert "$5,330.31" in chunk["text"]
    print("test_to_calculation_rag_chunk_shape: PASSED")


if __name__ == "__main__":
    test_extract_annual_income_dollar_sign()
    test_extract_annual_income_keyword_anchored()
    test_extract_annual_income_none_when_absent()
    test_extract_annual_income_bare_number_not_matched()
    test_extract_annual_income_none_when_compound_query()
    test_extract_annual_income_same_figure_repeated_still_resolves()
    test_extract_filing_status_head_of_household()
    test_extract_filing_status_married_variants()
    test_extract_filing_status_single()
    test_extract_filing_status_none_when_absent()
    test_extract_filing_status_none_when_two_distinct_statuses_named()
    test_extract_filing_status_same_status_repeated_still_resolves()
    test_extract_num_dependents_explicit_number()
    test_extract_num_dependents_qualifying_children_phrasing()
    test_extract_num_dependents_word_number()
    test_extract_num_dependents_zero_explicit()
    test_extract_num_dependents_defaults_to_zero_when_unmentioned()
    test_extract_num_dependents_none_when_ambiguous()
    test_extract_num_dependents_none_when_conflicting_counts_signaled()
    test_extract_tax_year_explicit()
    test_extract_tax_year_defaults_to_current_year()
    test_extract_household_params_full_query_resolves()
    test_extract_household_params_resolves_with_qualifying_children_phrasing()
    test_extract_household_params_none_when_income_missing()
    test_extract_household_params_none_when_filing_status_missing()
    test_extract_household_params_none_when_dependents_ambiguous()
    test_extract_household_params_resolves_state()
    test_extract_household_params_none_when_compound_comparison_query()
    test_real_calculation_known_scenario()
    test_to_calculation_rag_chunk_shape()
