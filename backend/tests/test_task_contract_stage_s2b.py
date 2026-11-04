"""Stage S2b: contract classification fixes from the tuning-set failures of
the S1 gold set (the held-back questions were not used). No model, database
or network.
"""
import pytest

from app.orchestration.task_contract import _inline_items, build_task_contract


def _first(query):
    return build_task_contract(query).retrieval[0]


@pytest.mark.parametrize("query, fact, countries", [
    ("What is the superannuation guarantee rate in Australia?", "rate", ["AUSTRALIA"]),
    ("What is the current RBA cash rate?", "rate", ["AUSTRALIA"]),
    ("What is the current federal funds target range?", "rate", ["US"]),
    ("Above what taxable income does UAE corporate tax apply at 9%?", "threshold", ["UAE"]),
    ("Do qualifying free zone persons pay corporate tax in the UAE?", "rule", ["UAE"]),
    ("What is the distance selling threshold for Northern Ireland sales to EU consumers?", "threshold", ["UK"]),
])
def test_official_figures_and_rules_are_recognised(query, fact, countries):
    requirement = _first(query)
    assert requirement.needs_official and requirement.fact_type == fact and requirement.jurisdictions == countries


def test_a_dated_reference_rate_is_an_exchange_rate():
    requirement = _first("What was the USD to INR reference rate on 31 December 2024?")
    assert requirement.needs_official and requirement.connector == "exchange_rate" and requirement.period.kind == "year"


@pytest.mark.parametrize("query", ["What is the internal rate of return on this project?", "What is the current ratio?",
                                   "What is the discount rate?", "Explain why central banks change interest rates."])
def test_rates_without_an_official_subject_are_not_official(query):
    assert not _first(query).needs_official


def test_the_other_partys_country_is_not_the_tax_country():
    requirement = _first("I'm a freelance developer in Bangalore billing a US client ₹30 lakh a year. "
                         "Do I need GST registration and do I charge GST?")
    assert requirement.jurisdictions == ["INDIA"]
    assert "irs.gov" not in requirement.official_domains


def test_a_scenarios_dates_are_not_a_period_asked_about():
    requirement = _first("Kestrel Logistics Ltd reports under IFRS. On 1 January 2026 it leased a depot for 5 years. "
                         "Annual payments of £24,000 are paid at the end of each year, and the interest rate implicit in "
                         "the lease is 7%. Calculate the initial lease liability.")
    assert not requirement.needs_official and requirement.period.kind == "unspecified"


def test_an_inline_numbered_list_is_split_in_the_contract():
    contract = build_task_contract("Questions to Answer: 1. Calculate the depreciation on equipment costing £30,000 over "
                                   "3 years with no residual value. 2. What is the current UK corporation tax rate?")
    assert [(r.needs_official, r.fact_type) for r in contract.retrieval] == [(False, "calculation"), (True, "rate")]


@pytest.mark.parametrize("text", ["Revenue grew 3.5 percent. Costs rose 2. Margins fell.", "Step 2. Do this. 1. Then that.",
                                  "1. A single item."])
def test_only_a_list_numbered_from_one_is_split(text):
    assert _inline_items(text) == []


@pytest.mark.parametrize("query", [
    "Income Tax Valuation Allowances (ASC 740). Vanguard Biotech has a gross deferred tax asset of $800,000. "
    "1. The valuation allowance adjustment. 2. How it flows through the income statement. 3. The journal entry.",
    "Questions to Answer: 1. Calculate the VAT on £1,000 at 20%. 2. Prepare the income statement.",
])
def test_the_finer_split_does_not_change_the_production_decisions(query):
    # Statements and VAT amount are decided on the shared splitter's parts,
    # as before S2b; the finer split is recorded only.
    from app.orchestration.case_text import request_part
    from app.orchestration.statement_rules import is_statement_request
    from app.orchestration.task_contract import _PART_LABEL, vat_amount_requested, _part
    from app.orchestration.websearch import sub_questions
    shared = [_part(text) for text in sub_questions(request_part(query))]
    contract = build_task_contract(query)
    assert contract.output_constraints.statements_requested == any(
        is_statement_request(_PART_LABEL.sub("", part.text, count=1)) for part in shared)
    assert contract.output_constraints.vat_amount_requested == vat_amount_requested(shared, query)
