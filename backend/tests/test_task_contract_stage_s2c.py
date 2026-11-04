"""Stage S2c: contract classification fixes from the second tuning set
(DEV2). The held-back sets (original 44, fresh 29, HOLDOUT3 40) were not used.
No model, database or network.
"""
import pytest

from app.orchestration.task_contract import build_task_contract


def _first(query):
    return build_task_contract(query).retrieval[0]


@pytest.mark.parametrize("query, fact", [
    ("What percentage VAT do UK restaurants charge on hot food?", "rate"),
    ("How much GST applies to two-wheelers in India now?", "rate"),
    ("How much is the UK marriage allowance?", "threshold"),
    ("What's the UK VAT registration limit?", "threshold"),
    ("What is the US estate tax exemption for 2026?", "threshold"),
    ("What is the late fee for GSTR-1 in India?", "rule"),
    ("Do US states charge sales tax on digital products?", "rule"),
])
def test_official_figures_and_rules_in_new_wordings(query, fact):
    requirement = _first(query)
    assert requirement.needs_official and requirement.fact_type == fact


@pytest.mark.parametrize("query", [
    "How do registration thresholds affect compliance costs?",
    "Explain the difference between a filing deadline and a filing extension.",
    "Explain the effective interest rate method for amortised cost.",
    "Explain the valuation allowance for deferred tax assets.",
])
def test_conceptual_questions_naming_thresholds_deadlines_or_rates_are_not_official(query):
    assert not _first(query).needs_official


def test_a_valuation_allowance_is_not_a_tax_allowance():
    assert _first("What is a valuation allowance under ASC 740?").fact_type != "threshold"


def test_a_tax_amount_with_the_users_figures_stays_a_calculation():
    requirement = _first("How much VAT is due on £10,000 of sales at 20%?")
    assert not requirement.needs_official and requirement.fact_type == "calculation"
